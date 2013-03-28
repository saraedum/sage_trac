from trac.core import *
from trac.web.chrome import *
from trac.util.translation import gettext as _
from trac.prefs import IPreferencePanelProvider
from trac.admin.api import IAdminCommandProvider
from trac.util.text import printout
from tracrpc.api import IXMLRPCHandler
import subprocess, os

_home = '/home/www-data'
_gitolite_keydir = os.path.join(_home, 'gitolite', 'keydir')
_gitolite_update = os.path.join(_home, 'bin', 'gitolite-update')

class UserDataStore(Component):
    def save_data(self, user, dictionary):
        """
        Saves user data for user.
        """
        self._create_table()
        with self.env.db_transaction as db:
            cursor = db.cursor()
            for key, value in dictionary.iteritems():
                try:
                    cursor.execute('INSERT INTO "user_data_store" VALUES (%s, %s, %s)', (user, key, value))
                except:
                    cursor.execute('REPLACE INTO "user_data_store" VALUES (%s, %s, %s)', (user, key, value))

    def get_data(self, user):
        """
        Returns a dictionary with all data keys
        """
        self._create_table()
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute('SELECT key, value FROM "user_data_store" WHERE "user"=%s', (user,))
            return {key:value for key, value in cursor}

    def get_data_all_users(self):
        """
        Returns a dictionary with all data keys
        """
        self._create_table()
        return_value = {}
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute('SELECT "user", key, value FROM "user_data_store"')
            for user, key, value in cursor:
                if return_value.has_key(user):
                    return_value[user][key] = value
                else:
                    return_value[user] = {key: value}
        return return_value

    def _create_table(self):
        with self.env.db_transaction as db:
            cursor = db.cursor()
            cursor.execute('SELECT * FROM information_schema.tables WHERE "table_name"=%s', ('user_data_store',))
            if not cursor.rowcount:
                cursor.execute('CREATE TABLE "user_data_store" ( "user" text, key text, value text, UNIQUE ( "user", key ) )')

class SshKeysPlugin(Component):
    implements(IPreferencePanelProvider, IAdminCommandProvider, IXMLRPCHandler)

    def __init__(self):
        self._user_data_store = UserDataStore(self.compmgr)

    # IPreferencePanelProvider methods
    def get_preference_panels(self, req):
        yield ('sshkeys', _('SSH keys'))

    def render_preference_panel(self, req, panel):
        if req.method == 'POST':
            new_ssh_keys = set(key.strip() for key in req.args.get('ssh_key').split('\n'))
            if new_ssh_keys:
                self.setkeys(req, new_ssh_keys)
                add_notice(req, 'Your ssh key has been saved.')
            req.redirect(req.href.prefs(panel or None))

        return 'prefs_ssh_keys.html', self._user_data_store.get_data(req.authname)

    # IAdminCommandProvider methods
    def get_admin_commands(self):
        yield ('sshkeys listusers', '',
               'Get a list of users that have a SSH key registered',
               None, self._do_listusers)
        yield ('sshkeys dumpkey', '<user>',
               "export the <user>'s SSH key to stdout",
               None, self._do_dump_key)

    # AdminCommandProvider boilerplate

    def _do_listusers(self):
         for user in self._listusers():
              printout(user)

    def _do_dump_key(self, user):
        printout(self._getkey(user))

    # Gitolite exporting
    def _export_to_gitolite(self, user, keys):
        for i,key in enumerate(keys):
            d = hex(i)[2:]
            while len(d) < 2:
                d = '0'+d
            f = open(os.path.join(_gitolite_keydir, d, user+'.pub'), 'w')
            f.write(key)
            f.close()
        process = subprocess.Popen(_gitolite_update)
        process.wait()

    # general functionality
    def _listusers(self):
        all_data = self._user_data_store.get_data_all_users()
        for user, data in all_data.iteritems():
            if data.has_key('ssh_keys'):
                yield user

    def _getkeys(self, user):
        return self._user_data_store.get_data(user)['ssh_keys'].split('\n')

    def _setkeys(self, user, keys):
        self._export_to_gitolite(user, keys)
        self._user_data_store.save_data(user, {'ssh_keys': '\n'.join(keys)})


    # RPC boilerplate
    def listusers(self, req):
        return list(self._listusers())

    def getkeys(self, req):
        return self._getkeys(req.authname)

    def setkeys(self, req, keys):
        keys = set(keys)
        if len(keys) > 0xff:
            add_warning(req, 'We only support using your first 256 ssh keys.')
        return self._setkeys(req.authname, keys)

    def addkeys(self, req, keys):
        new_keys = self.getkeys(req)
        new_keys.extend(keys)
        self.setkeys(req, new_keys)

    def addkey(self, req, key):
        self.addkeys(req, (key,))

    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return "sshkeys"

    def xmlrpc_methods(self):
        yield (None, ((list,),), self.listusers)
        yield (None, ((list,),), self.getkeys)
        yield (None, ((None,list),), self.setkeys)
        yield (None, ((None,list),), self.addkeys)
        yield (None, ((None,str),), self.addkey)
