import klampt
from klampt.math import vectorops as vops
from klampt.math import se3
from klampt.io import loader

if __name__=="__main__":
    import sys
    if len(sys.argv) != 4:
        print "robot_to_mesh.py: converts an articulated robot to a simple mesh"
        print "file.  Outputs in .tri format, which can be converted to OFF using"
        print "tri2off.py"
        print
        print "Usage: python robot_to_mesh.py robot config mesh"
        exit(0)
    robotfn = sys.argv[1]
    configfn = sys.argv[2]
    meshfn = sys.argv[3]
    #load the robot file
    world = klampt.WorldModel()
    robot = world.loadRobot(robotfn)
    if robot.getName()=='':
        print "Unable to load robot file",robotfn
        exit(1)
    fconfig = open(configfn,'r')
    for line in fconfig:
        q = loader.readVector(line)
        robot.setConfig(q)
        break
    fconfig.close()

    unionPoints = []
    unionTris = []
    for i in range(robot.numLinks()):
        T = robot.getLink(i).getTransform()
        geom = robot.getLink(i).getGeometry()
        t = geom.type()
        if t=="TriangleMesh":
            trimesh = geom.getTriangleMesh()
            tris = []
            for index in xrange(0,len(trimesh.indices),3):
                tris.append(trimesh.indices[index:index+3])
            points = []
            for index in xrange(0,len(trimesh.vertices),3):
                points.append(trimesh.vertices[index:index+3])
            offset = len(unionPoints)
            #apply transformation
            points = [se3.apply(T,pt) for pt in points]
            unionPoints += points
            #offset triangle indices by number of existing points
            unionTris += [(a+offset,b+offset,c+offset) for (a,b,c) in tris]
    print "Writing to",meshfn,"..."
    f = open(meshfn,'w')
    f.write(str(len(unionPoints))+'\n')
    for pt in unionPoints:
        f.write('%g %g %g\n'%tuple(pt))
    f.write(str(len(unionTris))+'\n')
    for tri in unionTris:
        f.write('%d %d %d\n'%tuple(tri))
    f.close()
