#!/usr/bin/env python3

from dataclasses import dataclass
import struct
import click
import sys
import os.path

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
        cylinders = data[0x20] + (data[0x22] << 8)
        heads = data[0x24]
        sectors = data[0x26]
        click.echo(f'Disk name : {name}')
        click.echo(f'C/H/S : {cylinders}/{heads}/{sectors}')
        expected_size = cylinders * heads * sectors * 512
        if fsize != expected_size:
            click.secho(f'ERROR: file expected size is {expected_size}, but actual is {fsize}', fg="red")
            sys.exit(-1)

        return Disk(name, cylinders, heads, sectors)

def format_cylinder(file, disk, num):
    file.seek(disk.block_size() * num, 0)
    write_zeros(file, 32)

@cli.command()
@click.argument('image')
@click.option('-n', '--name', type=str, default="ORAO")
@click.option('-c', '--cylinders', type=int, default=124)
@click.option('-h', '--heads', type=int, default=16)
@click.option('-s', '--sectors', type=int, default=63)
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
        write_byte(out, int(cylinders & 0xff))
        write_byte(out, (cylinders >> 8) & 0xff)
        write_byte(out, heads & 0xff)
        write_byte(out, sectors & 0xff)
        write_zeros(out, 236)
        cnt = cylinders * heads * sectors - 1
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
def dir(image):
    """Directory list"""
    disk = check_image(image)
    click.echo('')
    click.echo('Directory list:')
    free = disk.cylinders - 1
    click.echo("FILENAME         T START  END  UNK  U")
    click.echo("=====================================")
    with open(image, "rb+") as file:
        for i in range(1, disk.cylinders):
            file.seek(disk.block_size() * i, 0)
            data = file.read(0x40)
            if data[0]==0x00:
                break
            if data[0]==0xff:
                continue
            name = extract_name(data)
            start_addr = data[0x20] | data[0x22] << 8
            end_addr = data[0x24] | data[0x26] << 8
            unk_addr = data[0x28] | data[0x2a] << 8
            file_type = chr(data[0x2c])
            unk_byte = data[0x2e]
            click.echo(f"{name:16} {file_type}  {start_addr:04X} {end_addr:04X} {unk_addr:04X} {unk_byte:02X}")
            free -=1

    click.echo('')
    click.echo(f'{free} BLOCKS FREE')

@cli.command()
@click.argument('image')
@click.argument('filename')
def extract(image, filename):
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
            if name == filename:
                start_addr = data[0x20] | data[0x22] << 8
                end_addr = data[0x24] | data[0x26] << 8
                data_size = end_addr - start_addr + 1
                found = True
                click.echo(f'Writing file "{filename}"')
                with open(name, "wb") as f:
                    file.seek(disk.block_size() * i + 512, 0)
                    for i in range(0,data_size):
                        f.write(file.read(1))
                        _ = file.read(1)

    if not found:
        click.secho(f'ERROR: file "{filename}" not found !', fg="red")
        sys.exit(-1)        

if __name__ == '__main__':
    cli()
