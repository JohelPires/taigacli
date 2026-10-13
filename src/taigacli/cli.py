from __future__ import annotations

import sys

import click

from taigacli import commands
from taigacli.api import Api
from taigacli.config import api_url
from taigacli.errors import CliError
from taigacli.resources import RESOURCE_CANONICAL, RESOURCE_HELP, RESOURCE_SPECS
from taigacli.theme import ui_init


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

# alias (or command name) -> command name; RESOURCE_CANONICAL maps to api path
ALIAS_TO_COMMAND: dict[str, str] = {}
for _spec_name, (_api_key, _aliases) in RESOURCE_SPECS.items():
    ALIAS_TO_COMMAND[_spec_name] = _spec_name
    for _alias in _aliases:
        ALIAS_TO_COMMAND[_alias] = _spec_name


class TaigaGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        # bare aliases ("story 1343") resolve to the canonical command's
        # click.Command instance: same params/callback, alias name
        command_name = ALIAS_TO_COMMAND.get(cmd_name, cmd_name)
        if command_name != cmd_name:
            base = super().get_command(ctx, command_name)
            if base is None:
                return None
            return click.Command(
                cmd_name,
                callback=base.callback,
                params=base.params,
                help=base.help,
                short_help=base.short_help,
                context_settings=getattr(base, "context_settings", {}) or {},
            )
        return super().get_command(ctx, cmd_name)


@click.group(cls=TaigaGroup, context_settings=CONTEXT_SETTINGS)
@click.option("--json", is_flag=True, help="raw JSON output")
@click.option("--plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def taiga(ctx, json, plain):
    """Terminal-first command-line client for Taiga boards.

    Single file of mind, package underneath: list, inspect, set statuses,
    and export tickets as markdown.
    """
    ctx.ensure_object(dict)
    ctx.obj["group_json"] = bool(json)
    ctx.obj["group_plain"] = bool(plain)


def _ui(ctx) -> None:
    ctx.ensure_object(dict)
    j = bool(ctx.params.get("cmd_json") or ctx.obj.get("group_json"))
    p = bool(ctx.params.get("cmd_plain") or ctx.obj.get("group_plain"))
    ctx.obj["json"] = j
    ctx.obj["plain"] = p
    ui_init(plain=p)


def _api() -> Api:
    return Api()


@taiga.command(help="list open userstories/tasks/issues assigned to me")
@click.option("--limit", type=int, default=None)
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def mine(ctx, limit, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_mine(_api(), ctx, limit)


@taiga.command(name="login", help="sign in and cache an auth token")
@click.option("--username", "-u", default=None, help="Taiga username or email")
@click.option("--password", default=None, help="Taiga password (prefer the prompt)")
@click.option(
    "--remember/--no-remember",
    default=True,
    help="keep the password in the OS keyring so tokens renew silently (default: remember)",
)
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def login_cmd(ctx, username, password, remember, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_login(api_url(), username, password, ctx, remember=remember)


@taiga.command(name="logout", help="forget the cached auth token")
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def logout_cmd(ctx, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_logout(ctx)


@taiga.command(name="whoami", help="the signed-in account")
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def whoami(ctx, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_whoami(_api(), ctx)


@taiga.command(name="project", help="the resolved project")
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def project(ctx, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_project(_api(), ctx)


@taiga.command(name="help", help="show available commands and usage")
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
def help_cmd(cmd_json, cmd_plain):
    click.echo(taiga.get_help(click.get_current_context()))


def _make_resource_command(name: str):
    def _resource_cmd(ctx, ref, limit, filters, md_path, force, cmd_json, cmd_plain):
        _ui(ctx)
        resource = RESOURCE_CANONICAL[name]
        api = _api()
        if md_path and resource == "memberships":
            raise CliError("members have no ticket to export - drop --md")
        if ref is not None:
            if md_path:
                commands.cmd_get_md(api, ctx, resource, ref, md_path, force)
            else:
                commands.cmd_get(api, ctx, resource, ref)
        else:
            if md_path:
                raise CliError("Give a REF: --md exports one item")
            commands.cmd_list(api, ctx, resource, limit, list(filters))

    # apply decorators innermost (closest to fn) first, click.command outermost
    fn = click.pass_context(_resource_cmd)
    fn = click.argument("ref", required=False, type=int, metavar="REF")(fn)
    fn = click.option("--force", "-f", "force", is_flag=True, default=False, help="overwrite an existing file without asking")(fn)
    fn = click.option("--md", "md_path", metavar="DIR", type=click.Path(), default=None, help="write the item as markdown into DIR; the file is named from the ticket title")(fn)
    fn = click.option("--filter", "filters", multiple=True, help="repeatable; key=value")(fn)
    fn = click.option("--limit", type=int, default=None, help="cap the number of listed results")(fn)
    fn = click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")(fn)
    fn = click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")(fn)
    fn = click.command(name, help=RESOURCE_HELP[name], short_help=RESOURCE_HELP[name])(fn)
    return fn


for _name in RESOURCE_SPECS:
    if _name == "timeline":
        @taiga.command("timeline", help=RESOURCE_HELP["timeline"])
        @click.option("--limit", type=int, default=None)
        @click.option("--filter", "filters", multiple=True, help="repeatable; key=value")
        @click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
        @click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
        @click.pass_context
        def _timeline_cmd(ctx, limit, filters, cmd_json, cmd_plain):
            _ui(ctx)
            commands.cmd_list(_api(), ctx, "timeline", limit, list(filters))
        continue
    taiga.add_command(_make_resource_command(_name))


@taiga.command(
    name="set",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="change an item's status (e.g. set 1344 --in-review)",
)
@click.argument("tokens", nargs=-1, type=click.UNPROCESSED, metavar="[resource] <ref>")
@click.option("--dry-run", is_flag=True, help="show the change without saving")
@click.option("--status", default=None, help="target status by name, slug or id (instead of a --flag)")
@click.option("--json", "cmd_json", is_flag=True, default=False, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, default=False, help="no color, ASCII only")
@click.pass_context
def set_cmd(ctx, tokens, dry_run, status, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_set(_api(), ctx, list(tokens), status, dry_run)


def main() -> None:
    try:
        taiga(obj={"loaded": True})
    except CliError as e:
        _report(e)
        sys.exit(1)


def _report(e: CliError) -> None:
    from taigacli.render import paint
    from taigacli.theme import g

    print(paint(g("dot"), "danger") + " " + paint(str(e), "danger"), file=sys.stderr)
