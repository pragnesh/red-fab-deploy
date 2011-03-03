from fabric.api import *

def init():
	pass

def up(tagname):
	""" Update the code to the latest revision """
	run('svn up %s' % (
		os.path.join(env.conf['SRC_DIR'], tagname)))

def push(tagname):
	""" Check out the code to the remote repo """
	if tagname == 'trunk':
		dirname = os.path.join(env.conf['REPO'],tagname), 
	else:
		dirname = os.path.join(env.conf['REPO'],env.conf['VCS_TAGS'],tagname), 
	run('svn co %s %s' % (dirname,
		os.path.join(env.conf['SRC_DIR'],tagname)))

def export(tagname):
	""" Export the repo with tagname to /tmp/<tagname> """
	if tagname == 'trunk':
		dirname = os.path.join(env.conf['REPO'],tagname), 
	else:
		dirname = os.path.join(env.conf['REPO'],env.conf['VCS_TAGS'],tagname), 
	run('svn export %s %s' % (dirname,
		os.path.join(env.conf['SRC_DIR'],tagname)))
	
def configure():
	""" Configure the repo """
	pass

