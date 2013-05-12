# A graveyard for snippets removed from the project files.


# INTERMEDIATE 1) generate keypair for session
print "\nGenerating temporary RSA keypair for SSH authentication..."
from Crypto.PublicKey import RSA
keypair = RSA.generate(2048, os.urandom)
private_key = keypair.exportKey()
public_key = keypair.exportKey('OpenSSH')
pem = '/tmp/pzcluster.pem'
pemf = open(pem, 'w')
pemf.writelines(private_key)
pemf.close()
novakey = nova.keypairs.create('pzcluster', public_key)
print "\t[fingerprint=%s]" % novakey.fingerprint
# ...
# remove any keypairs
print "Removing keypair %s..." % novakey.fingerprint
nova.keypairs.delete('pzcluster')