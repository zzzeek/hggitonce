import argparse
from . import base


def main(argv=None):
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(help="sub-command help")


    subparser = subparsers.add_parser("convert",
                                help="convert an hg repo to git")
    subparser.set_defaults(cmd=base.hg_to_git)
    subparser.add_argument("hg_repo", help="Path to hg repo")
    subparser.add_argument("dest", help="where to put the git repo")

    subparser = subparsers.add_parser("subrevs",
                    help="Convert all hg revs in a text file to git revs")
    subparser.set_defaults(cmd=base.translate_file_revs)
    subparser.add_argument("mapfile", help="Path to rev file")
    subparser.add_argument("input", help="path to input file")

    args = parser.parse_args(argv)

    cmd = args.cmd

    cmd(args)

if __name__ == '__main__':
    main()