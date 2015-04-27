from Util import log, LogLevel, setLogLevel
setLogLevel(LogLevel.Trace)

log(LogLevel.Info, "Loading...")

from twisted.internet import reactor, protocol, task

from Network import BasicUserSession, SSHFactoryFactory

    

def main():

    import World
    log(LogLevel.Notice, 'Initializing world...')
    world = World.getWorld()
    world.db.db_get_user('admin')

    log(LogLevel.Debug, "Setting up ServerFactory")
    factory = protocol.ServerFactory()
    factory.protocol = BasicUserSession
    reactor.listenTCP(8888, factory)

    reactor.listenTCP(8822, SSHFactoryFactory(world))
    log(LogLevel.Notice, 'Now listening for connections.')
    log(LogLevel.Debug, 'Launching reactor.run() main loop')

    reactor.run()

if __name__ == '__main__': main()
