def setup_cli():
    import click

    from ..registry import Registry

    @click.group()
    @click.version_option(version=Registry.get_version(), prog_name=Registry.cli_title)
    def cli():
        pass

    commands = Registry.get_commands()
    for command in commands.values():
        click_cmd = command.get_cli_command(command)
        click_args = command.get_cli_args().values()
        for arg in click_args:
            click_cmd = arg(click_cmd)
        cli.add_command(click_cmd)

    return cli()


run = setup_cli()
