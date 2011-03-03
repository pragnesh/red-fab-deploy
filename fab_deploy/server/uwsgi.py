from fabric.api import *
from fabric.colors import *
from fabric.contrib.files import exists

from fab_deploy.package import package_install, package_update
from fab_deploy.utils import detect_os

def _uwsgi_is_installed():
	with settings(hide('stderr'), warn_only=True):
		option = run('which uwsgi')
	return option.succeeded

def uwsgi_install():
	""" Install uWSGI. """
	if _uwsgi_is_installed():
		warn(yellow('uWSGI is already installed'))
		return

	os = detect_os()
	options = {'lenny': '-t lenny-backports'}

	sudo('add-apt-repository ppa:uwsgi/release')
	package_update()
	package_install('uwsgi', options.get(os,''))

def uwsgi_setup():
	""" Setup uWSGI. """
	if not exists('/srv/active/'):
		warn(yellow('There is no active deployment'))
		return

	if exists('/etc/uwsgi/uwsgi-python2.6/uwsgi.ini'):
		warn(yellow('uWSGI has already been set up'))
	else:
		sudo('ln -s /srv/active/deploy/uwsgi.ini /etc/uwsgi/uwsgi-python2.6/uwsgi.ini')

def uwsgi_start():
	"""
	Start uwsgi sockets
	"""
	sudo('service uwsgi-python2.6 start')
	puts(green('Start uWSGI for %(host_string)s' % env))

def uwsgi_stop():
	"""
	Stop uwsgi sockets
	"""
	sudo('service uwsgi-python2.6 stop')

def uwsgi_restart():
	"""
	Restarts the uwsgi sockets.
	"""
	sudo('service uwsgi-python2.6 restart')

