#!/usr/bin/env python3

import sys
import os.path
import fnmatch
from dataclasses import dataclass
import struct
import click

@dataclass
class Disk:
    name : str
    cylinders : int
    heads : int
    sectors : int

    def block_size(self):
        return self.heads * self.sectors * 512

@click.group()
def cli():
    pass

def write_char(out, byte):
    out.write(byte)
    out.write(b'\x00')

def write_byte(out, byte):
    out.write(struct.pack('B',byte))
    out.write(b'\x00')

def write_zeros(out, num):
    out.write(b'\x00' * (num * 2))

def extract_name(data):
    name = ""
    for i in range(0, 0x20, 2):
        c = data[i]
        if c==0x04:
            break
        name = f"{name}{chr(c)}"
    return name

def check_image(image):
    with open(image, "rb") as file:
        file.seek(0,2)
        fsize = file.tell()
        file.seek(0)
        data = file.read(0x40)
        name = extract_name(data)
        cylinders = data[0x20] + (data[0x22] << 8) + 1
        heads = data[0x24]
        sectors = data[0x26]
        click.echo(f'Disk name : {name}')
        click.echo(f'C/H/S : {cylinders}/{heads}/{sectors}')
        expected_size = cylinders * heads * sectors * 512
        if expected_size > fsize:
            click.secho(f'ERROR: file expected size is {expected_size}, but actual is {fsize}', fg="red")
            sys.exit(-1)
        if fsize != expected_size:
            click.secho(f'WARNING: file expected size is {expected_size}, but actual is {fsize}', fg="yellow")

        return Disk(name, cylinders, heads, sectors)

def format_cylinder(file, disk, num):
    file.seek(disk.block_size() * num, 0)
    write_zeros(file, 32)

@cli.command()
@click.argument('image')
@click.option('-n', '--name', type=str, default="ORAO")
@click.option('-c', '--cylinders', type=int, default=490)
@click.option('-h', '--heads', type=int, default=4)
@click.option('-s', '--sectors', type=int, default=32)
def create(image, name, cylinders, heads, sectors):
    """Create image file"""
    click.echo('Creating image file')
    click.echo('')
    if os.path.isfile(image):
        click.confirm('Overwrite file?', abort=True)
    click.echo(f'Disk name : {name}')
    click.echo(f'C/H/S : {cylinders}/{heads}/{sectors}')
    with open(image, "wb") as out:
        for char in name:
            write_char(out, char.encode('ascii'))
        write_byte(out, 0x04)
        write_zeros(out, 15-len(name))
        # disk stores cylinder max value, not total number
        cylinders -= 1
        write_byte(out, int(cylinders & 0xff))
        write_byte(out, (cylinders >> 8) & 0xff)
        write_byte(out, heads & 0xff)
        write_byte(out, sectors & 0xff)
        write_zeros(out, 236)
        cnt = (cylinders + 1) * heads * sectors - 1
        write_zeros(out, cnt * 256)

@cli.command()
@click.argument('image')
def format(image):
    """Format image file"""
    disk = check_image(image)
    click.echo('')
    click.confirm('Do you want to continue?', abort=True)
    click.echo('')
    click.echo(f'Formatting image file "{image}"')
    with open(image, "rb+") as f:
        for i in range(1, disk.cylinders):
            format_cylinder(f, disk, i)

@cli.command()
@click.argument('image')
@click.argument('filter', type=str, default="*")
def dir(image, filter):
    """Directory list"""
    disk = check_image(image)
    click.echo('')
    click.echo('Directory list:')
    # remove cylinder 0 and use this as max number
    free = disk.cylinders - 2
    click.echo("FILENAME         T START  END AUTO  U")
    click.echo("=====================================")
    found = False
    with open(image, "rb+") as file:
        for i in range(1, disk.cylinders):
            file.seek(disk.block_size() * i, 0)
            data = file.read(0x40)
            if data[0]==0x00:
                break
            if data[0]==0xff:
                continue
            name = extract_name(data).strip()
            if fnmatch.fnmatch(name, filter):
                found = True
                start_addr = data[0x20] | data[0x22] << 8
                end_addr = data[0x24] | data[0x26] << 8
                auto_addr = data[0x28] | data[0x2a] << 8
                file_type = chr(data[0x2c])
                if not file_type in ['B', 'O']:
                    click.secho(f'ERROR: uknown {file_type} for file {name}', fg="red")
                unk_byte = data[0x2e]
                click.echo(f"{name:16} {file_type}  {start_addr:04X} {end_addr:04X} {auto_addr:04X} {unk_byte:02X}")
            free -=1
    if not found:
        click.echo('')
        click.echo(f'No files found for "{filter}"')
    click.echo('')
    click.echo(f'{free} BLOCKS FREE')

@cli.command()
@click.argument('image')
@click.argument('filter', type=str, default="*")
def extract(image, filter):
    """Extract file"""
    disk = check_image(image)
    click.echo('')
    found = False
    with open(image, "rb+") as file:
        for i in range(1, disk.cylinders):
            file.seek(disk.block_size() * i, 0)
            data = file.read(0x40)
            if data[0]==0x00:
                break
            if data[0]==0xff:
                continue
            name = extract_name(data).strip()
            if fnmatch.fnmatch(name, filter):
                found = True
                start_addr = data[0x20] | data[0x22] << 8
                end_addr = data[0x24] | data[0x26] << 8
                data_size = end_addr - start_addr + 1
                click.echo(f'Writing file "{name}"')
                blocks = data_size >> 8
                pos = 0
                with open(name, "wb") as f:
                    for b in range(0,blocks):
                        # This actually skip sector 0 of next head
                        if pos == disk.sectors-2:
                            pos += 1
                        file.seek(disk.block_size() * i + (pos + 1) * 512, 0)
                        for j in range(0,256):
                            f.write(file.read(1))
                            _ = file.read(1)
                        pos += 1

                    # This actually skip sector 0 of next head
                    if pos == disk.sectors-2:
                        pos += 1               
                    file.seek(disk.block_size() * i + (pos + 1) * 512, 0)
                    for j in range(0,data_size & 0xff):
                        f.write(file.read(1))
                        _ = file.read(1)

    if not found:
        click.secho(f'ERROR: No files found for "{filter}" !', fg="red")
        sys.exit(-1)

@cli.command()
@click.argument('image')
@click.argument('filter', type=str, default="*")
def erase(image, filter):
    """Erase file"""
    disk = check_image(image)
    click.echo('')
    found = False
    with open(image, "rb+") as file:
        for i in range(1, disk.cylinders):
            file.seek(disk.block_size() * i, 0)
            data = file.read(0x40)
            if data[0]==0x00:
                break
            if data[0]==0xff:
                continue
            name = extract_name(data).strip()
            if fnmatch.fnmatch(name, filter):
                found = True
                if click.confirm(f'Delete file "{name}" ?'):
                    file.seek(disk.block_size() * i, 0)
                    write_byte(file, 0xff)
                    write_zeros(file, 255)

    if not found:
        click.secho(f'ERROR: No files found for "{filter}" !', fg="red")
        sys.exit(-1)


class BasedIntParamType(click.ParamType):
    name = 'integer'

    def convert(self, value, param, ctx):
        try:
            if value[:2].lower() == '0x':
                return int(value[2:], 16)
            elif value[:1] == '0':
                return int(value, 8)
            return int(value, 10)
        except ValueError:
            self.fail('%s is not a valid integer' % value, param, ctx)

based_int = BasedIntParamType()

@cli.command()
@click.argument('image')
@click.argument('filename', type=str, default="")
@click.option('--type', type=str, default="O")
@click.option('--start', type=based_int, default="0x0000")
@click.option('--auto', type=based_int, default="0x0000")
def inject(image, filename, type, start, auto):
    """Inject file"""
    disk = check_image(image)
    click.echo('')
    if not os.path.exists(filename):
        click.secho(f'ERROR: Source file "{filename}" does not exists !', fg="red")
        sys.exit(-1)
    if type not in ["O", "B"]:
        click.secho(f'ERROR: Uknown type "{type}", accepting only "O" and "B" !', fg="red")
        sys.exit(-1)

    fsize = os.path.getsize(filename)
    fn = str(os.path.basename(filename))

    with open(image, "rb") as file:
        for i in range(1, disk.cylinders):
            file.seek(disk.block_size() * i, 0)
            data = file.read(0x40)
            if data[0]==0x00:
                break
            if data[0]==0xff:
                continue
            name = extract_name(data).strip()
            if fnmatch.fnmatch(name, filename):
                click.secho(f'ERROR: File "{filename}" exists !', fg="red")
                sys.exit(-1)

    saved = False

    with open(image, "rb+") as file:
        for i in range(1, disk.cylinders):
            file.seek(disk.block_size() * i, 0)
            data = file.read(0x40)
            if not(data[0]==0x00 or data[0]==0xff):
                continue
            file.seek(disk.block_size() * i, 0)
            # write filename
            for j in range(0,15):
                if j<len(fn):
                    char = fn[j]
                    write_char(file, char.encode('ascii'))
                else:
                    write_byte(file, 0x20)
            write_byte(file, 0x04)

            # write file metadata
            if type=="B":
                start_addr = 0x0400
                auto_addr = 0xB147
                file_type = 0x42 # B
                unk_byte = 0x12
            else:
                start_addr = start
                auto_addr = auto
                file_type = 0x4F # O
                unk_byte = 0x00

            end_addr = start_addr + fsize - 1

            write_byte(file, start_addr & 0xff)
            write_byte(file, (start_addr >> 8) & 0xff)
            write_byte(file, end_addr & 0xff)
            write_byte(file, (end_addr >> 8) & 0xff)
            write_byte(file, auto_addr & 0xff)
            write_byte(file, (auto_addr >> 8) & 0xff)
            write_byte(file, file_type)
            write_byte(file, unk_byte)

            blocks = fsize >> 8
            pos = 0
            with open(filename, "rb") as f:
                data = f.read()

                for b in range(0,blocks):
                    # This actually skip sector 0 of next head
                    if pos == disk.sectors-2:
                        pos += 1
                    file.seek(disk.block_size() * i + (pos + 1) * 512, 0)

                    for j in range(0,256):
                        write_byte(file, data[b*256 + j])
                    pos += 1

                # This actually skip sector 0 of next head
                if pos == disk.sectors-2:
                    pos += 1               
                file.seek(disk.block_size() * i + (pos + 1) * 512, 0)
                for j in range(0,fsize & 0xff):
                    write_byte(file, data[blocks*256 + j])

            saved = True
            break

    if not saved:
        click.secho(f'ERROR: No files found for "{filter}" !', fg="red")
        sys.exit(-1)

if __name__ == '__main__':
    cli()
