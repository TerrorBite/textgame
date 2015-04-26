from Util import log, LogLevel, setLogLevel
setLogLevel(LogLevel.Trace)

log(LogLevel.Info, "Loading...")

from twisted.internet import reactor, protocol, task
from twisted.cred import portal
from twisted.conch.ssh import session 
from twisted.conch.manhole_ssh import ConchFactory
from twisted.conch.insults import insults

from Network import BasicUserSession, SSHRealm, SSHFactory, SSHProtocol

def ssh_factory(world):
    """
    Creates and returns a factory class that produces SSH sessions.
    """
    realm = SSHRealm()
    # Set portal for SSHFactory so it knows how to auth users
    import Database
    SSHFactory.portal = portal.Portal(realm, [Database.CredentialsChecker(world.db)])
    return SSHFactory()
    

def main():

    import World
    log(LogLevel.Notice, 'Initializing world...')
    world = World.getWorld()
    world.db.db_get_user('admin')

    log(LogLevel.Debug, "Setting up ServerFactory")
    factory = protocol.ServerFactory()
    factory.protocol = BasicUserSession
    reactor.listenTCP(8888, factory)

    reactor.listenTCP(8822, ssh_factory(world))
    log(LogLevel.Notice, 'Now listening for connections.')
    log(LogLevel.Debug, 'Launching reactor.run() main loop')

    reactor.run()

if __name__ == '__main__': main()
