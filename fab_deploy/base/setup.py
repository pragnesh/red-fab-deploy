import sys, os
from fabric.api import task, run, sudo, execute, env, local, settings
from fabric.tasks import Task
from fabric.contrib.files import append, sed, exists, contains
from fabric.operations import get, put
from fabric.context_managers import cd

from fab_deploy import functions

class BaseSetup(Task):
    """
    Base server setup.

    Installs ipfilter and adds firewall config

    Sets up ssh so root cannot login and other logins must
    be key based.
    """

    # Because setup tasks modify the config file
    # they should always be run serially.
    serial = True
    setup_firewall = True
    setup_snmp = True

    def _set_profile(self):
        pass

    def _is_section_exists(self, section):
        if env.config_object.has_section(section):
            return True
        else:
            print "--------------------------"
            print ("Cannot find section %s. Please add [%s] into your"
                   " server.ini file." %(section, section))
            print ("If an instance has been created. You may run fab"
                   "setup.[server_type] to continue.")
            print "--------------------------"
            sys.exit(1)

    def _update_config(self, config_section):
        if not env.host_string:
            print "env.host_string is None, please specify a host by -H "
            sys.exit(1)

        self._is_section_exists(config_section)

        added = False
        cons = env.config_object.get_list(config_section,
                                env.config_object.CONNECTIONS)
        if not env.host_string in cons:
            added = True
            cons.append(env.host_string)
            env.config_object.set_list(config_section,
                                env.config_object.CONNECTIONS,
                                cons)


            ips = env.config_object.get_list(config_section,
                                env.config_object.INTERNAL_IPS)
            results = execute('utils.get_ip', None, hosts=[env.host_string])
            internal_ip = results[env.host_string]
            ips.append(internal_ip)

            env.config_object.set_list(config_section,
                                env.config_object.INTERNAL_IPS,
                                ips)
        return added

    def _save_config(self):
        env.config_object.save(env.conf_filename)

    def _add_snmp(self, config_section):
        if self.setup_snmp:
            execute('snmp.update_files', section=config_section)
            task = functions.get_task_instance('snmp.update_files')
            filename = task.get_section_path(config_section)
            execute('snmp.sync_single', filename=filename)

    def _secure_ssh(self):
        # Change disable root and password
        # logins in /etc/ssh/sshd_config
        sudo('sed -ie "s/^PermitRootLogin.*/PermitRootLogin no/g" /etc/ssh/sshd_config')
        sudo('sed -ie "s/^PasswordAuthentication.*/PasswordAuthentication no/g" /etc/ssh/sshd_config')
        self._ssh_restart()

    def _ssh_restart(self):
        raise NotImplementedError()

    def _update_firewalls(self, config_section):
        if self.setup_firewall:
            # Generate the correct file
            execute('firewall.update_files', section=config_section)

            task = functions.get_task_instance('firewall.update_files')
            filename = task.get_section_path(config_section)
            execute('firewall.sync_single', filename=filename)

            # Update any section where this section appears
            for section in env.config_object.server_sections():
                if config_section in env.config_object.get_list(section,
                                                    env.config_object.ALLOWED_SECTIONS):
                    execute('firewall.update_files', section=section)

class LBSetup(BaseSetup):
    """
    Setup a load balancer

    After base setup installs nginx setups a git repo. Then
    calls the deploy task.

    Once finished it calls ``nginx.update_allowed_ips``

    This is a serial task as it modifies local config files.
    """

    name = 'lb_server'

    config_section = 'load-balancer'

    git_branch = 'master'
    git_hook = None

    nginx_conf = 'nginx/nginx-lb.conf'

    def _add_remote(self, name=None):
        if not env.host_string in env.git_reverse:
            name = functions.get_remote_name(env.host_string, self.config_section,
                                             name=name)
            execute('local.git.add_remote', remote_name=name,
                                    user_and_host=env.host_string)
        return name

    def _install_packages(self):
        pass

    def _modify_others(self):
        task = functions.get_task_instance('setup.app_server')
        execute('nginx.update_allowed_ips', nginx_conf=task.nginx_conf,
                            section=self.config_section)

    def _transfer_files(self):
        execute('git.setup', branch=self.git_branch, hook=self.git_hook)
        execute('local.git.push', branch=self.git_branch)
        execute('local.git.reset_remote')

    def run(self, name=None):
        self._secure_ssh()
        self._set_profile()

        self._update_config(self.config_section)

        self._add_remote(name=name)

        # Transfer files first so all configs are in place.
        self._transfer_files()
        self._install_packages()
        self._setup_services()
        self._add_snmp(self.config_section)
        self._update_firewalls(self.config_section)
        self._save_config()

        execute('deploy', branch=self.git_branch)

        self._modify_others()

    def _setup_services(self):
        execute('nginx.setup', nginx_conf=self.nginx_conf)
        execute('nginx.control', start=True)

class AppSetup(LBSetup):
    """
    Setup a app-server

    Inherits from lb_setup so does everything it does.
    Also installs gunicorn, python, and other base packages.
    Runs the scripts/setup.sh script.

    Once finished it calls ``nginx.update_app_servers``

    This is a serial task as it modifies local config files.
    """

    name = 'app_server'

    config_section = 'app-server'
    settings_host = config_section

    nginx_conf = 'nginx/nginx.conf'

    packages = []

    def _set_profile(self):
        super(AppSetup, self)._set_profile()
        if self.settings_host and env.project_env_var:
            data = {'env_name': env.project_env_var,
                    'value' : self.settings_host}
            line = '%(env_name)s="%(value)s"; export %(env_name)s' % data
            append('/etc/profile', line, use_sudo=True)

    def _modify_others(self):
        task = functions.get_task_instance('setup.lb_server')
        execute('nginx.update_app_servers', nginx_conf=task.nginx_conf,
                        section=self.config_section)

    def _install_packages(self):
        raise NotImplementedError()

    def _install_venv(self):
        sudo('pip install virtualenv')
        run('sh %s/scripts/setup.sh production' % env.git_working_dir)

    def _setup_services(self):
        super(AppSetup, self)._setup_services()
        execute('gunicorn.setup', self.settings_host)
        execute('gunicorn.control', start=True)

class DBSetup(BaseSetup):
    """
    Setup a database server
    """
    name = 'db_server'
    config_section = 'db-server'

    def run(self, name=None):
        self._secure_ssh()
        self._set_profile()

        self._update_config(self.config_section)
        self._add_snmp(self.config_section)
        self._update_firewalls(self.config_section)
        dict = execute('postgres.master_setup', section=self.config_section,
                       save_config=True)
        self._save_config()

class SlaveSetup(DBSetup):
    """
    Set up a slave database server with streaming replication
    """
    name = 'slave_db'
    config_section = 'slave-db'

    def _get_master(self):
        cons = env.config_object.get_list('db-server',
                                          env.config_object.CONNECTIONS)
        n = len(cons)
        if n == 0:
            print ('I could not find db server in server.ini.'
                   'Did you set up a master server?')
            sys.exit(1)
        elif n == 1:
            master = cons[0]
        else:
            for i in range(1, n+1):
                print "[%2d ]: %s" %(i, cons[i-1])
            while True:
                choice = raw_input('I found %d servers in server.ini.'
                                   'Which one do you want to use as master? ' %n)
                try:
                    choice = int(choice)
                    master = cons[choice-1]
                    break
                except:
                    print "please input a number between 1 and %d" %n-1

        return master

    def run(self, name=None):
        """
        """
        self._secure_ssh()
        self._set_profile()

        self._update_config(self.config_section)
        master = self._get_master()
        self._add_snmp(self.config_section)
        self._update_firewalls(self.config_section)
        execute('postgres.slave_setup', master=master,
                section=self.config_section)
        self._save_config()

        # update firewall for db-server
        task = functions.get_task_instance('firewall.update_files')
        if task:
            filename = task.get_section_path('db-server')
            execute('firewall.sync_single', filename=filename, hosts=[master])

class DevSetup(AppSetup):
    """
    Setup a development server
    """
    name = 'dev_server'
    config_section = 'dev-server'
    settings_host = config_section
    git_branch = 'develop'

    def _modify_others(self):
        pass

    def _install_venv(self):
        sudo('pip install virtualenv')
        run('sh %s/scripts/setup.sh production development' % env.git_working_dir)

    def _setup_services(self):
        super(DevSetup, self)._setup_services()
        execute('postgres.master_setup', section=self.config_section)

class Control(Task):
    name = 'control'

    def stop(self):
        raise NotImplementedError()

    def start(self):
        raise NotImplementedError()

    def restart(self):
        raise NotImplementedError()

    def run(self, start=True, restart=False, stop=False, hosts=[]):
        if stop:
            self.stop()
        elif restart:
            self.restart()
        else:
            self.start()
