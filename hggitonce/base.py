from mercurial import ui, hg
from .git_handler import GitHandler, load_map, replace_hg_tags

def hg_to_git(args):
    hg_repo = args.hg_repo
    dest = args.dest

    ui_obj = ui.ui()

    repo = hg.repository(ui_obj, hg_repo)
    GitHandler(repo, ui_obj, dest, authors=args.authors).export_commits()

def translate_file_revs(args):
    mapfile = args.mapfile
    inputfile = args.input

    map_git = {}
    map_hg = {}
    map_hg_short = {}
    load_map(mapfile, map_git, map_hg, map_hg_short)
    with open(inputfile) as file_:
        print (
            replace_hg_tags(map_hg, map_hg_short, file_.read())
        )


def translate_trac_revs(args):
    from sqlalchemy import create_engine, MetaData, Table

    mapfile = args.mapfile

    map_git = {}
    map_hg = {}
    map_hg_short = {}
    load_map(mapfile, map_git, map_hg, map_hg_short)

    db = create_engine(args.dburl)

    m = MetaData()
    db_ticket_change = Table("ticket_change", m, autoload=True, autoload_with=db)
    db_ticket = Table("ticket", m, autoload=True, autoload_with=db)

    with db.begin() as conn:
        for ticket_change in conn.execute(db_ticket_change.select(
                                db_ticket_change.c.field.in_(
                                        ['comment', 'description']
                                )
                            )
                        ):
            result = conn.execute(
                db_ticket_change.update().where(
                        db_ticket_change.c.ticket == ticket_change.ticket
                    ).where(
                        db_ticket_change.c.time == ticket_change.time
                    ).where(
                        db_ticket_change.c.field == ticket_change.field
                    ).values(
                        oldvalue=replace_hg_tags(map_hg, map_hg_short,
                                                        ticket_change.oldvalue),
                        newvalue=replace_hg_tags(map_hg, map_hg_short,
                                                        ticket_change.newvalue)
                    )
            )
            assert result.rowcount == 1, result.rowcount

        for ticket in conn.execute(
                            db_ticket.select()
                        ):
            result = conn.execute(
                    db_ticket.update().where(
                            db_ticket.c.id == ticket.id
                        ).values(
                            description=replace_hg_tags(map_hg, map_hg_short,
                                                            ticket.description)
                        )
                    )
            assert result.rowcount == 1, result.rowcount

