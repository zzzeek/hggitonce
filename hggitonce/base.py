from mercurial import ui, hg
from .git_handler import GitHandler

def hg_to_git(args):
    hg_repo = args.hg_repo
    dest = args.dest

    ui_obj = ui.ui()


    repo = hg.repository(ui_obj, hg_repo)
    GitHandler(repo, ui_obj, dest).export_commits()

def translate_file_revs():
    pass
