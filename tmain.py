#!/usr/bin/env python
from twisted.internet import reactor, protocol

try:
    from textgame.Util import setup_logging, get_logger
finally:
    setup_logging(5)

from textgame.Network import BasicUserSession, SSHFactory
from textgame.World import World

log = get_logger("main")
log.info("Loading...")

if __name__ == '__main__':

    log.info('Initializing world...')
    world = World("Sqlite", "world.db")

    log.debug("Setting up ServerFactory")

    # Set up server factory for plaintext. Currently disabled as the code is not functional.
    # factory = protocol.ServerFactory()
    # factory.protocol = BasicUserSession
    # reactor.listenTCP(8888, factory)

    # Set up server factory for SSH access.
    reactor.listenTCP(8822, SSHFactory(world))
    log.info('Now listening for connections.')

    def on_shutdown():
        log.info("Shutting down...")
        world.close()

    reactor.addSystemEventTrigger('before', 'shutdown', on_shutdown)
    reactor.run()

    log.info("Shutdown is complete. Exiting.")

