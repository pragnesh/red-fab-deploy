import os.path

import fabric.api
import fabric.colors

from fab_deploy.file import link_exists
from fab_deploy.package import package_update, package_upgrade, package_install
from fab_deploy.utils import detect_os, append

def service(service, command):
	""" Give a command to a service """
	if service not in ['apache', 'nginx', 'uwsgi','mysql']:
		fabric.api.warn(fabric.api.colors('Service is not allowed: %s' % service))
		return
	fabric.api.sudo('service %s %s' % (service, command))

def get_public_ip():
	""" Returns the public IP address """
	command = """ifconfig eth0 | grep "inet addr" | awk -F: '{print $2}' | awk '{print $1}'"""
	return fabric.api.run(command)

def get_internal_ip():
	""" Returns the internal IP address """
	command = """ifconfig eth1 | grep "inet addr" | awk -F: '{print $2}' | awk '{print $1}'"""
	return fabric.api.run(command)

def print_hosts():
	""" Print the current env.hosts """
	print fabric.api.env.hosts

def set_hostname(hostname):
	""" Set the host name on a server """
	host_text = "127.0.0.1 %s" % hostname
	append('/etc/hosts', host_text, True)
	
	if hostname != get_hostname():
		fabric.api.sudo('hostname %s' % hostname)

def get_hostname():
	""" Get the host name on a server """
	return fabric.api.run('hostname')

def prepare_server():
	""" Prepares server: installs system packages. """
	setup_backports()
	install_common_software()

def setup_backports():
	""" Adds backports repo to apt sources. """
	os = detect_os()
	backports = {
		'lenny'    : 'http://backports.debian.org/debian-backports lenny-backports main contrib non-free',
		'squeeze'  : 'http://backports.debian.org/debian-backports squeeze-backports main contrib non-free',
		'lucid'    : 'http://archive.ubuntu.com/ubuntu lucid-backports main universe multiverse restricted',
		'maverick' : 'http://archive.ubuntu.com/ubuntu maverick-backports main universe multiverse restricted',
	}

	if os in backports:
		fabric.api.puts(fabric.colors.green("Installing available backports for %s" % os))
		return

	fabric.api.run("echo 'deb %s' > /etc/apt/sources.list.d/backports.sources.list" % backports[os])
	with fabric.api.settings(warn_only = True):
		package_update()
		package_upgrade()

def install_common_software():
	""" Installs common system packages. """
	common_packages = [
		'ack-grep',
		'build-essential',
		'curl',
		'gcc',
		'ipython',
		'libcurl3-dev',
		'libjpeg-dev',
		'libssl-dev',
		'ntp',
		'psmisc',
		'python2.6',
		'python2.6-dev',
		'python-imaging',
		'python-mysqldb',
		'python-pip',
		'python-setuptools',
		'python-software-properties',
		'python-virtualenv',
		'rsync',
		'screen',
		'subversion',
		'zlib1g-dev',
	]
	extra_packages = {
		'lenny': [],
		'sqeeze': [],
		'lucid': [],
		'maverick': [],
	}

	os = detect_os()
	if os not in extra_packages:
		fabric.api.abort(fabric.colors.red('Your OS (%s) is currently unsupported.' % os))

	with fabric.api.settings(warn_only = True):
		package_update()
		package_upgrade()

	package_install(common_packages + extra_packages[os])

	vcs_options = {'lenny': '-t lenny-backports'}
	package_install(['mercurial', 'git-core'], vcs_options.get(os, "") + "--no-install-recommends")

def usage_disk():
	""" Return disk usage """
	fabric.api.run("df -kP")

def usage_mem():
	""" Return memory usage """
	fabric.api.run("cat /proc/meminfo")

def usage_cpu():
	""" Return cpu usage """
	fabric.api.run("cat /proc/stat")

def usage_system():
	""" Return system usage stats """
	usage_disk()
	usage_mem()
	usage_system()

