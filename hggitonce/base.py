from mercurial import ui, hg
from .git_handler import GitHandler, load_map, replace_hg_tags


def hg_to_git(args):
    hg_repo = args.hg_repo
    dest = args.dest

    ui_obj = ui.ui()


    repo = hg.repository(ui_obj, hg_repo)
    GitHandler(repo, ui_obj, dest).export_commits()

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



