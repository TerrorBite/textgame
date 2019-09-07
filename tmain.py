#!/usr/bin/env python
from textgame.Util import log, LogLevel, setLogLevel, pip_install
setLogLevel(LogLevel.Trace)

log(LogLevel.Info, "Loading...")

try:
    from twisted.internet import reactor, protocol, task
except ImportError as e:
    log(LogLevel.Warn, "Failed to load Twisted Framework.")
    # Ask the user politely about these packages
    if pip_install('twisted', 'cryptography') == False:
        log(LogLevel.Fatal, "Cannot continue without the Twisted framework installed.")
        import traceback
        traceback.print_exc()
        exit(1)
    from twisted.internet import reactor, protocol, task

from textgame.Network import BasicUserSession, create_ssh_factory

    

def main():

    from textgame import World
    log(LogLevel.Notice, 'Initializing world...')
    world = World.getWorld() # Note: Currently, World is a singleton
    #world.db.db_get_user('admin')

    log(LogLevel.Debug, "Setting up ServerFactory")

    # Set up server factory for plaintext.
    factory = protocol.ServerFactory()
    factory.protocol = BasicUserSession
    reactor.listenTCP(8888, factory)

    # Set up server factory for SSH access.
    reactor.listenTCP(8822, create_ssh_factory(world))
    log(LogLevel.Notice, 'Now listening for connections.')
    log(LogLevel.Debug, 'Launching reactor.run() main loop')

    def onShutdown():
        log(LogLevel.Notice, "Shutting down...")
        world.close()

    reactor.addSystemEventTrigger('before', 'shutdown', onShutdown)
    reactor.run()

if __name__ == '__main__': main()
