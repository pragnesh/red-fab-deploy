import os
import sys
from uuid import uuid4

from fabric.api import run, sudo, env, local, hide, settings
from fabric.contrib.files import append, sed, exists, contains
from fabric.context_managers import prefix
from fabric.operations import get, put
from fabric.context_managers import cd

from fabric.tasks import Task

class PostgresInstall(Task):
    """
    Install postgresql on server

    install postgresql package;
    enable postgres access from localhost without password;
    enable all other user access from other machines with password;
    setup a few parameters related with streaming replication;
    database server listen to all machines '*';
    create a user for database with password.
    """

    name = 'master_setup'
    db_version = '9.1'

    encrypt = 'md5'
    hba_txts = ('local   all    postgres                     trust\n'
                'local   all    all                          password\n'
                '# # IPv4 local connections:\n'
                'host    all    all         127.0.0.1/32     %(encrypt)s\n'
                '# # IPv6 local connections:\n'
                'host    all    all         ::1/128          %(encrypt)s\n'
                '# # IPv4 external\n'
                'host    all    all         0.0.0.0/0        %(encrypt)s\n')

    postgres_config = {
        'listen_addresses':  "'*'",
        'wal_level':         "hot_standby",
        'wal_keep_segments': "32",
        'max_wal_senders':   "5",
        'archive_mode':      "on" }

    def _get_data_dir(self, db_version):
        return os.path.join('/var', 'pgsql', 'data%s' %db_version)

    def _setup_parameter(self, file, **kwargs):
        for key, value in kwargs.items():
            origin = "#%s =" %key
            new = "%s = %s" %(key, value)
            sudo('sed -i "/%s/ c\%s" %s' %(origin, new, file))

    def _install_package(self, db_version=None):
        sudo("pkg_add postgresql%s-server" %db_version)
        sudo("pkg_add postgresql%s-replicationtools" %db_version)
        sudo("svcadm enable postgresql:pg%s" %db_version)

    def _setup_hba_config(self, data_dir=None, encrypt=None):
        """
        enable postgres access without password from localhost
        """
        hba_conf = os.path.join(data_dir, 'pg_hba.conf')
        kwargs = {'data_dir':data_dir, 'encrypt':encrypt}
        hba_txts = self.hba_txts % kwargs

        if exists(hba_conf, use_sudo=True):
            sudo("echo '%s' > %s" %(hba_txts, hba_conf))
        else:
            print ('Could not find file %s. Please make sure postgresql was '
                   'installed and data dir was created correctly.'%hba_conf)
            sys.exit()

    def _setup_postgres_config(self, data_dir=None, config=None):
        postgres_conf = os.path.join(data_dir, 'postgresql.conf')

        if exists(postgres_conf, use_sudo=True):
            self._setup_parameter(postgres_conf, **config)
        else:
            print ('Could not find file %s. Please make sure postgresql was '
                   'installed and data dir was created correctly.' %postgres_conf)
            sys.exit()

    def _setup_archive_dir(self, data_dir):
        archive_dir = os.path.join(data_dir, 'wal_archive')
        sudo("mkdir -p %s" %archive_dir)
        sudo("chown postgres:postgres %s" %archive_dir)

        return archive_dir

    def _restart_db_server(self, db_version):
        sudo('svcadm restart postgresql:pg%s' %db_version)

    def _create_user(self):
        username = raw_input("Nowe we are creating a database user, please "
                             "specify a username: ")
        # 'postgres' is postgresql superuser
        while username == 'postgres':
            username = raw_input("Sorry, you are not allowed to use postgres "
                                 "as username, please choose another one: ")
        run("sudo su postgres -c 'createuser -D -S -R -P %s'" %username)

    def run(self, db_version=None, encrypt=None, *args, **kwargs):
        if not db_version:
            db_version = self.db_version
        db_version = ''.join(db_version.split('.')[:2])
        data_dir = self._get_data_dir(db_version)

        if not encrypt:
            encrypt = self.encrypt

        self._install_package(db_version=db_version)
        archive_dir = self._setup_archive_dir(data_dir)
        self.postgres_config['archive_command'] = ("'cp %s %s/wal_archive/%s'"
                                                   %('%p', data_dir, '%f'))

        self._setup_hba_config(data_dir, encrypt)
        self._setup_postgres_config(data_dir=data_dir,
                                    config=self.postgres_config)

        self._restart_db_server(db_version)
        self._create_user()


class ReplicationSetup(PostgresInstall):
    """
    Set up master-slave streaming replication: slave node
    """

    name = 'slave_setup'

    postgres_config = {
        'listen_addresses': "'*'",
        'wal_level':      "hot_standby",
        'hot_standby':    "on"}

    def _get_master_db_version(self, master):
        command = ("ssh %s psql --version | head -1 | awk '{print $3}'" %master)
        version_string = local(command, capture=True)
        version = ''.join(version_string.split('.')[:2])

        return version

    def _setup_recovery_conf(self, master_ip, password, data_dir):
        wal_dir = os.path.join(data_dir, 'wal_archive')
        recovery_conf = os.path.join(data_dir, 'recovery.conf')

        txts = (("standby_mode = 'on'\n") +
                ("primary_conninfo = 'host=%s " %master_ip) +
                    ("port=5432 user=replicator password=%s'\n" %password) +
                ("trigger_file = '/tmp/pgsql.trigger'\n") +
                ("restore_command = 'cp -f %s/%s </dev/null'\n"
                    %(wal_dir, '%f %p')) +
                ("archive_cleanup_command = 'pg_archivecleanup %s %s'\n"
                    %(wal_dir, "%r")))

        sudo('rm %s' %recovery_conf)
        sudo('touch %s' %recovery_conf)
        append(recovery_conf, txts, use_sudo=True)
        sudo('chown postgres:postgres %s' %recovery_conf)

    def _modify_hba_config(self, data_dir, hba_txt):
        hba_conf= os.path.join(data_dir, 'pg_hba.conf')
        append(hba_conf, hba_txt, use_sudo=True)

    def _ssh_key_exchange(self, master, slave):
        """
        set up ssh key, so that master can access slave without password via ssh
        """
        ssh_dir = '/var/pgsql/.ssh'
        for host in [master, slave]:
            with settings(host_string=host):
                sudo('mkdir -p %s' %ssh_dir)
                sudo('chown -R postgres:postgres %s' %ssh_dir)
                sudo('chmod -R og-rwx %s' %ssh_dir)

        with settings(host_string=master):
            rsa = os.path.join(ssh_dir, 'id_rsa')
            rsa_pub = os.path.join(ssh_dir, 'id_rsa.pub')
            run('sudo su postgres -c "ssh-keygen -t rsa -f %s -N \'\'"' %rsa)
            with hide('output'):
                pub_key = sudo('cat %s' %rsa_pub)

        with settings(host_string=slave):
            authorized_keys = os.path.join(ssh_dir, 'authorized_keys')
            with hide('output', 'running'):
                run('sudo su postgres -c "echo %s >> %s"'
                    %(pub_key, authorized_keys))

    def run(self, encrypt=None, *args, **kwargs):
        cons = env.config_object.get_list('db-server',
                                          env.config_object.CONNECTIONS)
        if len(cons) > 1:
            print ('Sorry, there are two db-servers in server.ini, and I don\'t'
                   'know how to setup two master servers')
            sys.exit()
        elif len(cons) < 1:
            print ('I could not find db server in server.ini.'
                   'Did you set up a master server?')
            sys.exit()
        else:
            master = cons[0]
            master_ip = master.split('@')[1]

        db_version = self._get_master_db_version(master=master)
        data_dir = self._get_data_dir(db_version)
        slave = env.host_string
        slave_ip = slave.split('@')[1]
        replicator_pass = uuid4().hex

        self._install_package(db_version=db_version)
        sudo('svcadm disable postgresql:pg%s' %db_version)

        self._ssh_key_exchange(master, slave)

        with settings(host_string=master):
            c1 = ('CREATE USER replicator REPLICATION LOGIN ENCRYPTED '
                  'PASSWORD \'%s\';' %replicator_pass)
            run('psql -U postgres -c "%s"' %c1)

            hba_txt = 'host\treplication\treplicator\t%s/32\tmd5' %slave_ip
            self._modify_hba_config(data_dir=data_dir, hba_txt=hba_txt)

            run('psql -U postgres -c "SELECT pg_start_backup(\'backup\', true)"')
            run('sudo su - postgres -c "rsync -av --exclude postmaster.pid '
                '--exclude pg_xlog %s/ postgres@%s:%s/"'%(data_dir, slave_ip, data_dir))
            run('psql -U postgres -c "SELECT pg_stop_backup()"')

        self._setup_postgres_config(data_dir=data_dir,
                                    config=self.postgres_config)
        self._setup_archive_dir(data_dir)
        self._setup_recovery_conf(master_ip=master_ip,
                                  password=replicator_pass, data_dir=data_dir)

        if not encrypt:
            encrypt = self.encrypt
        self._setup_hba_config(data_dir, encrypt)
        hba_txt = ('host\treplication\treplicator\t%s/32\tmd5\n'
                   'host\treplication\treplicator\t%s/32\tmd5'
                   %(slave_ip, master_ip))
        self._modify_hba_config(data_dir=data_dir, hba_txt=hba_txt)

        sudo('svcadm enable postgresql:pg%s' %db_version)
        print('password for replicator on master node is %s' %replicator_pass)

master_setup = PostgresInstall()
slave_setup = ReplicationSetup()
