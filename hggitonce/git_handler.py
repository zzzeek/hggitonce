################################################################
#
# Adapted from https://bitbucket.org/durin42/hg-git/.
#
################################################################

import os
import urllib
import re

from dulwich.objects import Commit, parse_timezone
from dulwich.pack import apply_delta
from dulwich.repo import Repo

try:
    from mercurial import bookmarks
    bookmarks.update
except ImportError:
    from hgext import bookmarks

try:
    from mercurial.error import RepoError
except ImportError:
    from mercurial.repo import RepoError

from mercurial.i18n import _
from mercurial.node import hex as hex_  # this is just binascii.hexlify
from mercurial import util as hgutil

from . import hg2git


RE_GIT_AUTHOR = re.compile('^(.*?) ?\<(.*?)(?:\>(.*))?$')

RE_GIT_SANITIZE_AUTHOR = re.compile('[<>\n]')

RE_GIT_AUTHOR_EXTRA = re.compile('^(.*?)\ ext:\((.*)\) <(.*)\>$')

# Test for git:// and git+ssh:// URI.
# Support several URL forms, including separating the
# host and path with either a / or : (sepr)
RE_GIT_URI = re.compile(
    r'^(?P<scheme>git([+]ssh)?://)(?P<host>.*?)(:(?P<port>\d+))?'
    r'(?P<sepr>[:/])(?P<path>.*)$')

RE_NEWLINES = re.compile('[\r\n]')
RE_GIT_PROGRESS = re.compile('\((\d+)/(\d+)\)')

RE_AUTHOR_FILE = re.compile('\s*=\s*')


class GitHandler(object):
    mapfile = 'git-mapfile'
    tagsfile = 'git-tags'

    def __init__(self, dest_repo, ui, gitdir):
        self.repo = dest_repo
        self.ui = ui
        self.gitdir = gitdir

        self.init_author_file()

        self.paths = ui.configitems('paths')

        self.branch_bookmark_suffix = ui.config('git', 'branch_bookmark_suffix')

        self._map_git_real = {}
        self._map_hg_real = {}
        self._map_hg_short = {}
        self.load_tags()

    def path_join(self, path):
        return os.path.join(self.gitdir, path)

    def opener(self, fname, *args):
        return open(self.path_join(fname), *args)

    @property
    def _map_git(self):
      if not self._map_git_real:
        self.load_map()
      return self._map_git_real

    @property
    def _map_hg(self):
      if not self._map_hg_real:
        self.load_map()
      return self._map_hg_real

    # make the git data directory
    def init_if_missing(self):
        if os.path.exists(self.gitdir):
            self.git = Repo(self.gitdir)
        else:
            os.mkdir(self.gitdir)
            self.git = Repo.init_bare(self.gitdir)

    def init_author_file(self):
        self.author_map = {}
        if self.ui.config('git', 'authors'):
            f = open(self.repo.wjoin(
                self.ui.config('git', 'authors')))
            try:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    from_, to = RE_AUTHOR_FILE.split(line, 2)
                    self.author_map[from_] = to
            finally:
                f.close()

    ## FILE LOAD AND SAVE METHODS

    def map_set(self, gitsha, hgsha):
        map_set(
            gitsha, hgsha,
            self._map_git,
            self._map_hg,
            self._map_hg_short
        )

    def map_hg_get(self, gitsha):
        return self._map_git.get(gitsha)

    def map_git_get(self, hgsha):
        return self._map_hg.get(hgsha)

    def load_map(self):
        if os.path.exists(self.path_join(self.mapfile)):
            load_map(
                self.path_join(self.mapfile),
                self._map_git,
                self._map_hg,
                self._map_hg_short
            )

    def save_map(self):
        file = self.opener(self.mapfile, 'w+')
        for hgsha, gitsha in sorted(self._map_hg.iteritems()):
            file.write("%s %s\n" % (gitsha, hgsha))
        # If this complains that NoneType is not callable, then
        # atomictempfile no longer has either of rename (pre-1.9) or
        # close (post-1.9)
        getattr(file, 'rename', getattr(file, 'close', None))()

    def load_tags(self):
        self.tags = {}
        if os.path.exists(self.path_join(self.tagsfile)):
            for line in self.opener(self.tagsfile):
                sha, name = line.strip().split(' ', 1)
                self.tags[name] = sha

    def save_tags(self):
        file = self.path_opener(self.tagsfile, 'w+', atomictemp=True)
        for name, sha in sorted(self.tags.iteritems()):
            if not self.repo.tagtype(name) == 'global':
                file.write("%s %s\n" % (sha, name))
        # If this complains that NoneType is not callable, then
        # atomictempfile no longer has either of rename (pre-1.9) or
        # close (post-1.9)
        getattr(file, 'rename', getattr(file, 'close', None))()

    ## END FILE LOAD AND SAVE METHODS

    ## COMMANDS METHODS

    def export_commits(self):
        try:
            self.export_git_objects()
            self.export_hg_tags()
            self.update_references()
        finally:
            self.save_map()


    ## CHANGESET CONVERSION METHODS

    def export_git_objects(self):
        self.init_if_missing()

        nodes = [self.repo.lookup(n) for n in self.repo]
        export = [node for node in nodes if not hex_(node) in self._map_hg]
        total = len(export)
        if total:
            self.ui.note(_("exporting hg objects to git\n"))

        # By only exporting deltas, the assertion is that all previous objects
        # for all other changesets are already present in the Git repository.
        # This assertion is necessary to prevent redundant work.
        exporter = hg2git.IncrementalChangesetExporter(self.repo)

        for i, rev in enumerate(export):
            self.ui.progress('exporting', i, total=total)
            ctx = self.repo.changectx(rev)
            state = ctx.extra().get('hg-git', None)
            if state == 'octopus':
                self.ui.debug("revision %d is a part "
                              "of octopus explosion\n" % ctx.rev())
                continue
            self.export_hg_commit(rev, exporter)
        self.ui.progress('importing', None, total=total)


    # convert this commit into git objects
    # go through the manifest, convert all blobs/trees we don't have
    # write the commit object (with metadata info)
    def export_hg_commit(self, rev, exporter):
        self.ui.note(_("converting revision %s\n") % hex_(rev))

        oldenc = self.swap_out_encoding()

        ctx = self.repo.changectx(rev)
        extra = ctx.extra()

        commit = Commit()

        (time, timezone) = ctx.date()
        # work around to bad timezone offets - dulwich does not handle
        # sub minute based timezones. In the one known case, it was a
        # manual edit that led to the unusual value. Based on that,
        # there is no reason to round one way or the other, so do the
        # simplest and round down.
        timezone -= (timezone % 60)
        commit.author = self.get_git_author(ctx)
        commit.author_time = int(time)
        commit.author_timezone = -timezone

        if 'committer' in extra:
            # fixup timezone
            (name, timestamp, timezone) = extra['committer'].rsplit(' ', 2)
            commit.committer = name
            commit.commit_time = timestamp

            # work around a timezone format change
            if int(timezone) % 60 != 0: #pragma: no cover
                timezone = parse_timezone(timezone)
                # Newer versions of Dulwich return a tuple here
                if isinstance(timezone, tuple):
                    timezone, neg_utc = timezone
                    commit._commit_timezone_neg_utc = neg_utc
            else:
                timezone = -int(timezone)
            commit.commit_timezone = timezone
        else:
            commit.committer = commit.author
            commit.commit_time = commit.author_time
            commit.commit_timezone = commit.author_timezone

        commit.parents = []
        for parent in self.get_git_parents(ctx):
            hgsha = hex_(parent.node())
            git_sha = self.map_git_get(hgsha)
            if git_sha:
                if git_sha not in self.git.object_store:
                    raise hgutil.Abort(_('Parent SHA-1 not present in Git'
                                         'repo: %s' % git_sha))

                commit.parents.append(git_sha)

        commit.message = self.get_git_message(ctx)

        if 'encoding' in extra:
            commit.encoding = extra['encoding']

        for obj, nodeid in exporter.update_changeset(ctx):
            self.git.object_store.add_object(obj)

        tree_sha = exporter.root_tree_sha

        if tree_sha not in self.git.object_store:
            raise hgutil.Abort(_('Tree SHA-1 not present in Git repo: %s' %
                tree_sha))

        commit.tree = tree_sha

        self.git.object_store.add_object(commit)
        self.map_set(commit.id, ctx.hex())

        self.swap_out_encoding(oldenc)
        return commit.id

    def get_valid_git_username_email(self, name):
        r"""Sanitize usernames and emails to fit git's restrictions.

        The following is taken from the man page of git's fast-import
        command:

            [...] Likewise LF means one (and only one) linefeed [...]

            committer
                The committer command indicates who made this commit,
                and when they made it.

                Here <name> is the person's display name (for example
                "Com M Itter") and <email> is the person's email address
                ("cm@example.com[1]"). LT and GT are the literal
                less-than (\x3c) and greater-than (\x3e) symbols. These
                are required to delimit the email address from the other
                fields in the line. Note that <name> and <email> are
                free-form and may contain any sequence of bytes, except
                LT, GT and LF. <name> is typically UTF-8 encoded.

        Accordingly, this function makes sure that there are none of the
        characters <, >, or \n in any string which will be used for
        a git username or email. Before this, it first removes left
        angle brackets and spaces from the beginning, and right angle
        brackets and spaces from the end, of this string, to convert
        such things as " <john@doe.com> " to "john@doe.com" for
        convenience.

        TESTS:

        >>> from mercurial.ui import ui
        >>> g = GitHandler('', ui()).get_valid_git_username_email
        >>> g('John Doe')
        'John Doe'
        >>> g('john@doe.com')
        'john@doe.com'
        >>> g(' <john@doe.com> ')
        'john@doe.com'
        >>> g('    <random<\n<garbage\n>  > > ')
        'random???garbage?'
        >>> g('Typo in hgrc >but.hg-git@handles.it.gracefully>')
        'Typo in hgrc ?but.hg-git@handles.it.gracefully'
        """
        return RE_GIT_SANITIZE_AUTHOR.sub('?', name.lstrip('< ').rstrip('> '))

    def get_git_author(self, ctx):
        # hg authors might not have emails
        author = ctx.user()

        # see if a translation exists
        author = self.author_map.get(author, author)

        # check for git author pattern compliance
        a = RE_GIT_AUTHOR.match(author)

        if a:
            name = self.get_valid_git_username_email(a.group(1))
            email = self.get_valid_git_username_email(a.group(2))
            if a.group(3) != None and len(a.group(3)) != 0:
                name += ' ext:(' + urllib.quote(a.group(3)) + ')'
            author = self.get_valid_git_username_email(name) + ' <' + self.get_valid_git_username_email(email) + '>'
        elif '@' in author:
            author = self.get_valid_git_username_email(author) + ' <' + self.get_valid_git_username_email(author) + '>'
        else:
            author = self.get_valid_git_username_email(author) + ' <none@none>'

        if 'author' in ctx.extra():
            author = "".join(apply_delta(author, ctx.extra()['author']))

        return author

    def get_git_parents(self, ctx):
        def is_octopus_part(ctx):
            return ctx.extra().get('hg-git', None) in ('octopus', 'octopus-done')

        parents = []
        if ctx.extra().get('hg-git', None) == 'octopus-done':
            # implode octopus parents
            part = ctx
            while is_octopus_part(part):
                (p1, p2) = part.parents()
                assert not is_octopus_part(p1)
                parents.append(p1)
                part = p2
            parents.append(p2)
        else:
            parents = ctx.parents()

        return parents

    def get_git_message(self, ctx):
        extra = ctx.extra()

        message = ctx.description() + "\n"

        # TODO: convert changelog ids
        if 'message' in extra:
            message = "".join(apply_delta(message, extra['message']))

        message = replace_hg_tags(self._map_hg_real, self._map_hg_short, message)
        return message


    ## REFERENCES HANDLING

    def update_references(self):
        heads = self.local_heads()

        # Create a local Git branch name for each
        # Mercurial bookmark.
        for key in heads:
            git_ref = self.map_git_get(heads[key])
            if git_ref:
                self.git.refs['refs/heads/' + key] = self.map_git_get(heads[key])

    def export_hg_tags(self):
        for tag, sha in self.repo.tags().iteritems():
            if self.repo.tagtype(tag) in ('global', 'git'):
                tag = tag.replace(' ', '_')
                target = self.map_git_get(hex_(sha))
                if target is not None:
                    self.git.refs['refs/tags/' + tag] = target
                    self.tags[tag] = hex_(sha)
                else:
                    self.repo.ui.warn(
                        'Skipping export of tag %s because it '
                        'has no matching git revision.' % tag)

    def local_heads(self):
        d = dict(
            (k, hex_(v)) for
                k, v in  self.repo.branchtags().items()
        )
        if 'default' in d:
            d['master'] = d['default']
            del d['default']
        return d



    ## UTILITY FUNCTIONS

    def extract_hg_metadata(self, message):
        split = message.split("\n--HG--\n", 1)
        renames = {}
        extra = {}
        branch = False
        if len(split) == 2:
            message, meta = split
            lines = meta.split("\n")
            for line in lines:
                if line == '':
                    continue

                if ' : ' not in line:
                    break
                command, data = line.split(" : ", 1)

                if command == 'rename':
                    before, after = data.split(" => ", 1)
                    renames[after] = before
                if command == 'branch':
                    branch = data
                if command == 'extra':
                    before, after = data.split(" : ", 1)
                    extra[before] = urllib.unquote(after)
        return (message, renames, branch, extra)


    # Stolen from hgsubversion
    def swap_out_encoding(self, new_encoding='UTF-8'):
        try:
            from mercurial import encoding
            old = encoding.encoding
            encoding.encoding = new_encoding
        except ImportError:
            old = hgutil._encoding
            hgutil._encoding = new_encoding
        return old

def map_set(gitsha, hgsha, map_git, map_hg, map_hg_short):
    map_git[gitsha] = hgsha
    map_hg[hgsha] = gitsha
    map_hg_short[hgsha[0:12]] = gitsha

def load_map(mapfile, map_git, map_hg, map_hg_short):
    with open(mapfile) as file_:
        for line in file_:
            gitsha, hgsha = line.strip().split(' ', 1)
            map_set(gitsha, hgsha, map_git, map_hg, map_hg_short)


def replace_hg_tags(hg_map, hg_short_map, text):
    def repl(m):
        hash_ = m.group(1)
        if hash_ in hg_short_map:
            return hg_short_map[hash_]
        elif hash_ in hg_map:
            return hg_map[hash_]
        else:
            return hash_
    return re.sub(
                r'\b([a-f0-9]{12,})\b', repl, text
            )
