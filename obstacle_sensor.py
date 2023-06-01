# ==============================================================================
# -- ObstacleSensor() ----------------------------------------------------------
# https://carla.readthedocs.io/en/latest/ref_sensors/#obstacle-detector
# https://github.com/carla-simulator/carla/blob/master/Docs/ref_sensors.md#obstacle-detector
# -- Versuch: Anscheinend gibt es einen Sensor, welcher Hindernisse erkennen kann..
# source code analog zu dem Source aus  https://www.youtube.com/watch?v=om8klsBj4rc&t=14s, An in depth look at CARLA's sensors: https://www.youtube.com/redirect?event=video_description&redir_token=QUFFLUhqbm44LTE2dFRkMTRPSGZuYTg5QXM4NE9RWVJIZ3xBQ3Jtc0ttc01VdlZsYWhoTFZsVmZram14MUxYZEw0WXp4cFp6ZFcydXNSS2k2aUgyTGVNd052SzhFRHhyTDA0dGVrQ0hKN0dWN2EtMzNPQ0NiekVjcHlXMXB4UUpnelktb19pU0J2SHNJME5TeXpCanlzck9wQQ&q=https%3A%2F%2Fcarla-releases.s3.eu-west-3.amazonaws.com%2FDocs%2FSensors_code.zip&v=om8klsBj4rc
# ==============================================================================
class ObstacleSensor:

    __obstacle_sensor = None
    __camera = None
    __world = None
    __player = None
    __current_obstacle = []

    def getCurrentObstacleDictance(self, maxAlterDesHindernissesInMillis):
        try:
            if len(self.__current_obstacle) > 0:
                distance = self.__current_obstacle['distance']
                myTimeStamp = self.__current_obstacle['myTimeStamp']
                timeStamp = time.time()
                t_diff = timeStamp-myTimeStamp
                if (t_diff < maxAlterDesHindernissesInMillis):
                    return distance
                else: return 0.0
            else: return 0.0
        except Exception as e:
            print(type(e))  # the exception type
            print(e.args)  # arguments stored in .args
            print(e)  # __str__ allows args to be printed directly,
            return 0.0 #keine Hindernisse

    #Parameter: _player = carla-vehicle, _world is unsere lokale klasse World aus manual_control.py
    def __init__(self, _player, _world):
        self.__world = _world #Zeiger auf MyClientWorld wirde gemerkt
        self.__player = _player #Zeiger auf Vehicle wird gemerkt
        self.__attach(self.__world, self.__player) #Obstacle Sensor wird erzeugt und das Vehicle PER CALLBAcK-Funktion gebunden.

    #sihe https://github.com/carla-simulator/carla/blob/master/Docs/ref_sensors.md
    #https://carla.readthedocs.io/en/0.9.5/cameras_and_sensors/#sensorotherobstacle
    #Doku zum bostacle sensor https://github.com/carla-simulator/carla/blob/master/Docs/ref_sensors.md#obstacle-detector
    def __attach(self, _world, _vehicle):
        bp_lib = _world.world.get_blueprint_library() #BluePrint-Library wird ermittelt
        # Sensor wird dem Fahrzeug angehängt
        obstacle_bp = bp_lib.find('sensor.other.obstacle') #der Obscatale Sensoer Blue print wird ermittelt
        obstacle_bp.set_attribute('hit_radius', '0.5') #Parameter aus dem fremden Source, nicht klar, was genau sie machen, es akkan aber in der Doku von Carla nachgelesen werden. Radius of the trace
        obstacle_bp.set_attribute('distance', '50') #Distance to throw the trace to. https://carla.readthedocs.io/en/0.9.5/cameras_and_sensors/#sensorotherobstacle
        self.__obstacle_sensor = _world.world.spawn_actor(obstacle_bp, carla.Transform(), attach_to=_vehicle) #Der Sensor wird erstellt(gespawnt) und an das Fahrzeug gebunden
        # Starte den Sensor, damit daten empfangen werden können
        self.__obstacle_sensor.listen(lambda event: self.__obstacle_callback(event)) # Diese Methode ist gekürzt, da keine Camera-Parameter mehr benötight.
        print("ObstacleSensor.__attached(...)")
#
    def __obstacle_callback(self, event): # call back des Obstacle Sensors
        if 'vehicle' in event.other_actor.type_id:  # "static" wird vermutlich alle unbeweglichen Objekte wie ein Gebäude oder ein gepraktes Auto ausschließen
            self.__current_obstacle = {'type_id': event.other_actor.type_id, 'frame': event.frame, 'timestamp':event.timestamp, 'actor':event.actor, 'other_actor':event.other_actor, 'distance':event.distance, 'myTimeStamp':time.time()}
