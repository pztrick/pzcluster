import time
import sys
import os

from novaclient import client
from fabric.api import env
from fabric.api import settings as fabric_settings
from fabric.tasks import execute

import settings
from fabfile import (local_ssh_agent, deploy, start_broker, start_workers, start_client)
from worker import Worker


# CONFIG 1) Configure fabric to execute tasks asynchronously over SSH
env.warn_only = True
env.connection_attempts = 10
env.timeout = 10
env.user = 'ubuntu'
env.forward_agent = True
env.parallel = True

# CONFIG 2) Where is our SSH keypair
KEY_PATH = os.path.join(os.environ['HOME'], '.ssh/id_rsa')

# CONFIG 3) These values are defined in settings.py (gitignore'd)
username = settings.USERNAME
password = settings.PASSWORD
tenant = settings.TENANT
endpoint = settings.ENDPOINT
git_url = settings.GIT_URL
git_folder = settings.GIT_FOLDER
git_host_keys = settings.GIT_HOST_KEYS
rabbitmq_username = settings.RABBITMQ_USERNAME
rabbitmq_password = settings.RABBITMQ_PASSWORD

# Connect to nova client
nova = client.Client(2, username, password, tenant, endpoint)

# Report any existing VMs on cluster
other_server_names = reduce(lambda a, x: "%s\n\t* %s" % (a, x),
                            map(lambda x: x.name, nova.servers.list()),
                            '')
print "\nThese servers were already up and will not be affected: ", other_server_names

# INPUT 1) number of workers
number_of_instances = int(raw_input("\nHow many workers?\n: "))

# INPUT 2) size of compute instance (RAM, CPU, etc)
print "\nWhich flavor would you like to provision?"
flavors = nova.flavors.list()
for i in range(len(flavors)):
    print "\t%i - %s" % (i, flavors[i].name)
flavor = flavors[int(raw_input(": "))]

# INPUT 3) operating system
print "\nWhich image would you like to install?"
images = nova.images.list()
for i in range(len(images)):
    print "\t%i - %s" % (i, images[i].name)
image = images[int(raw_input(": "))]

# INPUT 4) authenticate with ssh-agent for passwordless SSH authentication
print "\nAdding local RSA key to SSH agent..."
execute(local_ssh_agent, KEY_PATH)

workers = list()
novakey = None
try:
    # 1) upload local RSA key to openstack
    print "\nUploading local public key for injection into workers..."
    keyfile = open("%s.pub" % KEY_PATH, 'r')
    public_key = keyfile.read()
    keyfile.close()
    novakey = nova.keypairs.create('pzcluster', public_key)
    print "\t[fingerprint=%s]" % novakey.fingerprint

    # 2) Generate instances and attach public IP address
    fips = nova.floating_ips_bulk.findall(pool='public', instance_uuid=None)

    print "\nSpawning %i workers..." % number_of_instances
    for i in range(number_of_instances):
        name = 'pzcluster-%i' % i
        workers.append(Worker(nova, image, flavor, name, novakey.name))

    counter = 0
    while not all(worker.active for worker in workers):
        time.sleep(1)
        counter += 1
        sys.stdout.write("\r\tBuilding instances (%ss elapsed)" % counter)
        sys.stdout.flush()

    print "\n\tAssigning public IPs to instances..."
    for worker in workers:
        worker.assign_floating_ip(fips.pop().address)

    counter = 0
    sys.stdout.write("\r\tWaiting for public IPs (%ss elapsed)" % counter)
    sys.stdout.flush()
    while not all(worker.public_ip for worker in workers):
        time.sleep(1)
        counter += 1
        sys.stdout.write("\r\tWaiting for public IPs (%ss elapsed)" % counter)
        sys.stdout.flush()

    print "\n\nThese servers were created: ", \
        reduce(lambda a, x: "%s\n\t* %s" % (a, x),
               map(lambda x: "%s [private=%s] [public=%s]" % (x.name,
                                                              x.private_ip,
                                                              x.public_ip),
                   workers),
               '')

    print  # line
    counter = 0
    while not all(worker.listening for worker in workers):
        time.sleep(1)
        counter += 1
        sys.stdout.write("\rWaiting for system booting... (%is elapsed)" % counter)
        sys.stdout.flush()
    print  # line
    print  # line

    # 3) Configure Fabric to access our hosts
    env.hosts = list(worker.public_ip for worker in workers)
    env.roledefs.update({
        'broker': [workers[0].public_ip],
        'workers': [x.public_ip for x in workers[1:]]
    })
    broker_ip = workers[0].private_ip

    # 4) Work - install packages, deploy celery, execute client scripts
    execute(deploy, git_host_keys, git_url, git_folder)
    with fabric_settings(warn_only=False):  # abort main.py if broker fails to start
        execute(start_broker, rabbitmq_username, rabbitmq_password)
    execute(start_workers, git_folder, broker_ip, rabbitmq_username, rabbitmq_password)
    execute(start_client, git_folder, broker_ip, rabbitmq_username, rabbitmq_password)

finally:
    print "\nCleaning up..."

    # terminate any fabric SSH sessions
    from fabric.state import connections
    for key in connections.keys():
        print "Disconnecting from ssh://%s..." % key
        connections[key].close()

    # terminate any VMs that were created
    print "Terminating cluster instances..."
    for worker in workers:
        worker.instance.delete()

    # remove keypair from nova
    if novakey:
        print "Removing nova keypair %s..." % novakey.fingerprint
        novakey.delete()

    print "Session complete. All workers have been purged.\n"
