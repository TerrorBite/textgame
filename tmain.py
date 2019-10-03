#!/usr/bin/env python
from textgame.Util import setup_logging, pip_install
import logging

setup_logging(logging.DEBUG)
log = logging.getLogger()
log.info("Loading...")

try:
    from twisted.internet import reactor, protocol, task
except ImportError as e:
    log.warn("Failed to load Twisted Framework.")
    # Ask the user politely about these packages
    if pip_install('twisted', 'cryptography', 'bcrypt', 'pyasn1') == False:
        log.fatal("Cannot continue without the Twisted framework installed.")
        import traceback
        traceback.print_exc()
        exit(1)
    from twisted.internet import reactor, protocol, task

from textgame.Network import BasicUserSession, create_ssh_factory
from textgame.World import World

    

def main():

    log.info('Initializing world...')
    world = World("Sqlite", "world.db")

    log.debug("Setting up ServerFactory")

    # Set up server factory for plaintext.
    factory = protocol.ServerFactory()
    factory.protocol = BasicUserSession
    reactor.listenTCP(8888, factory)

    # Set up server factory for SSH access.
    reactor.listenTCP(8822, create_ssh_factory(world))
    log.info('Now listening for connections.')

    def onShutdown():
        log.info("Shutting down...")
        world.close()

    reactor.addSystemEventTrigger('before', 'shutdown', onShutdown)
    reactor.run()

if __name__ == '__main__': main()
