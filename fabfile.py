from fabric.api import roles, task, run, sudo, local, cd, settings, prefix, put

APT_PACKAGES_ALL = ["python-pip", "git", ]
APT_PACKAGES_BROKER = ["rabbitmq-server", ]
APT_PACKAGES_WORKER = ["supervisor", ]
PIP_PACKAGES = ["celery", ]


@task
def local_ssh_agent(KEY_FILE):
    local("ssh-add %s" % KEY_FILE)


@task
def sleep_for_cloudinit():
    """ Strange issue occurs when attempting apt-get update before cloudboot-init has finished
        Reference: http://serverfault.com/q/440569/144986 """
    run("sleep 15")


@task
def apt_update():
    sudo("apt-get update &> /dev/null")


@task
def apt_packages(apt_packages):
    """ Installs aptitude packages on VM """
    packages = reduce(lambda a, x: "%s %s" % (a, x), apt_packages, '')
    sudo("apt-get -y install %s &> /dev/null" % packages)


@task
def pip_packages():
    """ Installs python libraries on VM """
    packages = reduce(lambda a, x: "%s %s" % (a, x), PIP_PACKAGES, '')
    sudo("pip install %s &> /dev/null" % packages)


@task
def add_host_keys(public_keys):
    put('/tmp/cluster_known_hosts', '.ssh/known_hosts')


@task
def git_clone(git_url, git_folder):
    """ Clones the git project defined in settings.py """
    run("git clone %s %s &> /dev/null" % (git_url, git_folder))


@task
def exec_main_py(git_folder):
    """ Executes worker.py remotely, piping remote STDOUT to our Fabric console """
    with cd(git_folder):
        run("python main.py")


@task
def update_etc_hosts(address, hostname):
    sudo("echo '%s %s' | tee -a /etc/hosts" % (address, hostname))


@task
def deploy(public_keys, git_url, git_folder):
    with open('/tmp/cluster_known_hosts', 'w') as tmp:
        tmp.write(reduce(lambda a, x: "%s\n%s" % (a, x), public_keys))

    with settings(warn_only=False):
        sleep_for_cloudinit()
        apt_update()
        apt_packages(APT_PACKAGES_ALL)
        pip_packages()
        add_host_keys(public_keys)
        with cd("/"):
            sudo("mkdir %s" % git_folder)
            sudo("chmod 777 %s" % git_folder)
            git_clone(git_url, git_folder)


@roles('broker')
def start_broker(rabbitmq_username, rabbitmq_password):
    apt_packages(APT_PACKAGES_BROKER)
    # rabbitmq-server should be running after completing apt-get install
    sudo("rabbitmqctl add_user %s %s" % (rabbitmq_username, rabbitmq_password))
    # TODO: add vhost
    sudo("rabbitmqctl set_permissions -p / %s \".*\" \".*\" \".*\"" % rabbitmq_username)
    sudo("rabbitmqctl status")


@roles('workers')
def start_workers(git_folder, broker_ip, rabbitmq_username, rabbitmq_password):
    with settings(warn_only=False):
        apt_packages(APT_PACKAGES_WORKER)
        update_etc_hosts(broker_ip, "pzcluster-0")
        # Configure supervisord to run celery
        sudo("echo \"[program:celeryd]\ndirectory=/%s\nenvironment=RABBITMQ_USERNAME=%s,RABBITMQ_PASSWORD=%s\ncommand=celeryd --loglevel=INFO\nautostart=true\nautorestart=true\" | tee /etc/supervisor/conf.d/celeryd.conf" % (git_folder, rabbitmq_username, rabbitmq_password))
        sudo("supervisorctl update")
        sudo("supervisorctl restart celeryd")
    #with cd("/%s" % git_folder), prefix("export RABBITMQ_USERNAME=%s" % rabbitmq_username), prefix("export RABBITMQ_PASSWORD=%s" % rabbitmq_password):
    #            run("celery -A tasks worker --loglevel=debug")


@roles('broker')
def start_client(git_folder, broker_ip, rabbitmq_username, rabbitmq_password):
    # FIXME: this is currently the same as the broker machine, but it could be different later
    update_etc_hosts(broker_ip, "pzcluster-0")
    with cd("/%s" % git_folder), prefix("export RABBITMQ_USERNAME=%s" % rabbitmq_username), prefix("export RABBITMQ_PASSWORD=%s" % rabbitmq_password):
        run("python client.py")
