# Worker instance (wrapper for nova API's server instance)
import socket


class Worker(object):
    def __init__(self, client, image, flavor, name, key_name):
        self.client = client

        self.instance = self.client.servers.create(image=image,
                                                   flavor=flavor,
                                                   name=name,
                                                   key_name=key_name)

    @property
    def name(self):
        return self.instance.name

    @property
    def private_ip(self):
        self._update()
        try:
            return self.instance.addresses['private'][0]['addr']
        except:
            pass
        return None

    @property
    def public_ip(self):
        self._update()
        try:
            return self.instance.addresses['private'][1]['addr']
        except:
            pass
        return None

    @property
    def active(self):
        self._update()
        return self.instance.status == "ACTIVE"

    @property
    def listening(self):
        """ Determines if SSH is available """
        s = socket.socket()
        try:
            s.connect((self.public_ip, 22))
            return True
        except:
            return False
        finally:
            s.close()

    def assign_floating_ip(self, address):
        self.instance.add_floating_ip(address)

    def _update(self):
        """ Make a fresh call to nova API to get updated object information """
        self.instance = self.client.servers.get(self.instance.id)
