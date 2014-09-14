
from World import World

world = World()

print 'Ready to go!'

username = raw_input('Login as: ')
passwd = raw_input('Password: ')

player = world.connect(username, passwd)
if not player:
    print 'Invalid login.'
    world.close()
    exit(0)
else:

    print "Getting player's location"
    location = player.parent()

    print "Welcome, {0}! You are currently in: {1}\n{2}".format(player.name(), location.name(), location.desc(player))

    print "Getting player's inventory"
    print "You are carrying: {0}".format(', '.join(map(lambda x: x.name(), player.contents())))
world.close()
