from Util import log, LogLevel, setLogLevel
setLogLevel(LogLevel.Trace)

log(LogLevel.Info, "Starting up...")

from Network import UserSession
from twisted.internet import reactor, protocol, task

def main():


    log(LogLevel.Debug, "Setting up ServerFactory")
    factory = protocol.ServerFactory()
    factory.protocol = UserSession

    import World
    
    reactor.listenTCP(8888, factory)
    log(LogLevel.Notice, 'Listening for connections...')
    log(LogLevel.Debug, 'Launching reactor.run() main loop')

    reactor.run()

if __name__ == '__main__': main()
