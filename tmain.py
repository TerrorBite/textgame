from Util import log, LogLevel, setLogLevel, pip_install
setLogLevel(LogLevel.Trace)

log(LogLevel.Info, "Loading...")

try:
    from twisted.internet import reactor, protocol, task
except ImportError as e:
    log(LogLevel.Warn, "Failed to load Twisted Framework. Will try and install it...")
    if pip_install('twisted', 'cryptography') == False:
        log(LogLevel.Fatal, "Failed to install Twisted. Giving up.")
        import traceback
        traceback.print_exc()
        exit(1)
    from twisted.internet import reactor, protocol, task

from Network import BasicUserSession, SSHFactoryFactory

    

def main():

    import World
    log(LogLevel.Notice, 'Initializing world...')
    world = World.getWorld()
    #world.db.db_get_user('admin')

    log(LogLevel.Debug, "Setting up ServerFactory")
    factory = protocol.ServerFactory()
    factory.protocol = BasicUserSession
    reactor.listenTCP(8888, factory)

    reactor.listenTCP(8822, SSHFactoryFactory(world))
    log(LogLevel.Notice, 'Now listening for connections.')
    log(LogLevel.Debug, 'Launching reactor.run() main loop')

    def onShutdown():
        log(LogLevel.Notice, "Shutting down...")
        world.close()

    reactor.addSystemEventTrigger('before', 'shutdown', onShutdown)
    reactor.run()

if __name__ == '__main__': main()
