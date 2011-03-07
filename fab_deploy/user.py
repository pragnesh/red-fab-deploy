import os.path

import fabric.api
import fabric.colors
import fabric.contrib

from fab_deploy.file import file_attribs
from fab_deploy.utils import run_as

@run_as('root')
def provider_as_ec2(user='ubuntu',group='www-data'):
	""" Set up a provider similar to Amazon EC2 """
	user_create(user)
	ssh_keygen(user)
	ssh_get_key(user)
	ssh_authorize(user,'%s.id_dsa' % user)
	user_setup(user)
	group_user_add(group,user)
	grant_sudo_access(user)

def user_exists(user):
	""" 
	Determine if a user exists with given user.
	
	This returns the information as a dictionary
	'{"name":<str>,"uid":<str>,"gid":<str>,"home":<str>,"shell":<str>}' or 'None'
	if the user does not exist.
	"""
	with fabric.api.settings(fabric.api.hide('warnings','stderr','stdout'),warn_only=True):
		user_data = fabric.api.run("cat /etc/passwd | egrep '^%s:' ; true" % user)

	if user_data:
		u = user_data.split(":")
		return dict(name=u[0],uid=u[2],gid=u[3],home=u[5],shell=u[6])
	else:
		return None

def user_create(user, home=None, uid=None, gid=None, password=False):
	""" 
	Creates the user with the given user, optionally giving a specific home/uid/gid.

	By default users will be created without a password.  To create users with a
	password you must set "password" to True.
	"""
	options = []
	if home: options.append("-d '%s'" % home)
	if uid:  options.append("-u '%s'" % uid)
	if gid:  options.append("-g '%s'" % gid)
	if not password: options.append("--disabled-password")
	fabric.api.sudo("adduser %s '%s'" % (" ".join(options), user))

def user_setup(user):
	"""
	Copies a set of files into the home directory of a user
	"""
	u = user_exists(user)
	assert u, fabric.colors.red("User does not exist: %s" % user)
	home = u['home']

	templates = fabric.api.env.conf['FILES']
	for filename in ['.bashrc','.inputrc','.screenrc','.vimrc',]:
		fabric.api.put(os.path.join(templates,filename),os.path.join(home,filename))
	
	for path in ['.vim/filetype.vim','.vim/doc/NERD_tree.txt','.vim/plugin/NERD_tree.vim']:
		fabric.api.run('mkdir -p %s' % os.path.join(home,os.path.dirname(path)))
		fabric.api.put(os.path.join(templates,path),os.path.join(home,path))

def group_exists(name):
	"""
	Determine if a group exists with a given name.

	This returns the information as a dictionary
	'{"name":<str>,"gid":<str>,"members":<list[str]>}' or 'None'
	if the group does not exist.
	"""
	with fabric.api.settings(fabric.api.hide('warnings','stderr','stdout'),warn_only=True):
		group_data = fabric.api.run("cat /etc/group | egrep '^%s:' ; true" % (name))
	
	if group_data:
		name,_,gid,members = group_data.split(":",4)
		return dict(name=name,gid=gid,members=tuple(m.strip() for m in members.split(",")))
	else:
		return None

def group_create(name, gid=None):
	""" Creates a group with the given name, and optionally given gid. """
	options = []
	if gid: options.append("-g '%s'" % gid)
	fabric.api.sudo("addgroup %s '%s'" % (" ".join(options), name))

def group_user_exists(group, user):
	""" Determine if the given user is a member of the given group. """
	g = group_exists(group)
	assert g, fabric.colors.red("Group does not exist: %s" % group)
	
	u = user_exists(user)
	assert u, fabric.colors.red("User does not exist: %s" % user)
	
	return user in g["members"]

def group_user_add(group, user):
	""" Adds the given user to the given group. """
	if not group_user_exists(group, user):
		fabric.api.sudo('adduser %s %s' % (user, group))

def grant_sudo_access(user):
	""" Grants sudo access to a user. """
	u = user_exists(user)
	assert u, fabric.colors.red("User does not exist: %s" % user)

	text="%s\tALL=(ALL) NOPASSWD:ALL" % user
	fabric.contrib.files.append('/etc/sudoers',text,use_sudo=True)

def ssh_keygen(username):
	""" Generates a pair of DSA keys in the user's home .ssh directory."""
	d = user_exists(username)
	assert d, fabric.colors.red("User does not exist: %s" % username)

	home = d['home']
	if not fabric.contrib.files.exists(os.path.join(home, "/.ssh/id_dsa.pub")):
		fabric.api.run("mkdir -p %s" % os.path.join(home, "/.ssh"))
		fabric.api.run("ssh-keygen -q -t dsa -f '%s/.ssh/id_dsa' -N ''" % home)
		file_attribs(home + "/.ssh/id_dsa",     owner=username, group=username)
		file_attribs(home + "/.ssh/id_dsa.pub", owner=username, group=username)

def ssh_get_key(username):
	""" Get the DSA key pair from the server for a specific user """
	d = user_exists(username)
	home = d['home']

	pub_key = os.path.join(home,'.ssh/id_dsa.pub')
	sec_key = os.path.join(home,'.ssh/id_dsa')

	fabric.api.get(pub_key,local_path='%s.id_dsa.pub'%username)
	fabric.api.get(sec_key,local_path='%s.id_dsa'%username)

def ssh_authorize(username,key):
	""" 
	Adds a ssh key from passed file to user's authorized_keys on server. 
	
	SSH keys can be added at any time::

		fab ssh_authorize:"/home/ubuntu.id_dsa.pub"
	"""
	d = user_exists(username)
	keyf = os.path.join(d['home'],'/.ssh/authorized_keys')
	
	with open(os.path.normpath(key), 'r') as f:
		ssh_key = f.read()
	
	if fabric.contrib.files.exists(keyf):
		if not fabric.contrib.files.contains(keyf,ssh_key):
			fabric.contrib.files.append(keyf, ssh_key)
	else:
		fabric.api.put(key,keyf)

	fabric.api.sudo('chown -R %s:%s %s/.ssh' % (username, username,d['home']))
