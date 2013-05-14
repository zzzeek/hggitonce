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

    args = parser.parse_args(argv)

    cmd = args.cmd

    cmd(args)

if __name__ == '__main__':
    main()