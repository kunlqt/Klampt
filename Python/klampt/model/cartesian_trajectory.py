from trajectory import *
import ik
import config
from collections import deque
import math

def set_cartesian_constraints(x,constraints,solver):
	"""For x a workspace parameter setting (achieved via config.getConfig(constraints)),
	a set of constraints, and a IKSolver object, modifies the constraints
	and the solver so that the solver is setup to match the workspace parameter
	setting x."""
	config.setConfig(constraints,x)
	solver.clear()
	for c in constraints:
		solver.add(c)

def solve_cartesian(x,constraints,solver):
	"""For x a workspace parameter setting (achieved via config.getConfig(constraints)),
	a set of constraints, and a IKSolver object, returns True if the solver can find
	a solution (from the robot's current configuration). Returns True if successful."""
	set_cartesian_constraints(x,constraints,solver)
	return  solver.solve()

def _make_canonical(robot,constraints,startConfig,endConfig,solver):
	if not hasattr(constraints,'__iter__'):
		constraints = [constraints]
	for c in constraints:
		if isinstance(c,(int,str)):
			newconstraints = []
			for d in constraints:
				if isinstance(d,(int,str)):
					newconstraints.append(ik.objective(robot,d,R=so3.identity(),t=[0,0,0]))
				else:
					assert isinstance(d,IKObjective)
					newconstraints.append(d)
			if solver:
				newSolver = IKSolver(solver)
				newSolver.clear()
				for d in newconstraints:
					newSolver.add(d)
			else:
				newSolver = None
			constraints = newconstraints
			solver = newSolver
			break
	if solver == None:
		solver = ik.solver(constraints)
	if startConfig=='robot':
		startConfig = robot.getConfig()
	if endConfig=='robot':
		endConfig = robot.getConfig()
	return constraints,startConfig,endConfig,solver

def cartesian_interpolate_linear(robot,a,b,constraints,
	startConfig='robot',endConfig=None,
	delta=1e-2,
	solver=None,
	feasibilityTest=None,
	maximize=False):
	"""Resolves a continuous robot trajectory that interpolates between two cartesian points
	for specified IK constraints.  Note that the output path is only a kinematic resolution.
	It has time domain [0,1].

	Arguments:
	- robot: the RobotModel or SubRobotModel.
	- a, b: endpoints of the Cartesian trajectory.  Assumed derived from config.getConfig(constraints)
	- constraints: IKObjectives on the link or links that are constrained.  Or, they can be indices, or strings
	  in which case they constrain the transform of the link
	- startConfig: either 'robot' (configuration taken from the robot), a configuration, or None (any configuration)
	- endConfig: same type as startConfig.
	- delta: the maximum configuration space distance between points on the output path
	- solver: None, or a configured IKSolver on the given constraints
	- feasibilityTest: None, or a function f(q) that returns false when a configuration q is infeasible
	- maximize: if true, goes as far as possible along the path.

	Out: a RobotTrajectory that interpolates the Cartesian path, or None if none can be found.
	"""
	assert delta > 0,"Spatial resolution must be positive"
	constraints,startConfig,endConfig,solver = _make_canonical(robot,constraints,startConfig,endConfig,solver)

	assert startConfig != None,"Unable to cartesian interpolate without a start configuration"
	robot.setConfig(startConfig)
	set_cartesian_constraints(a,constraints,solver)
	if not solver.isSolved():
		if not solver.solve():
			print "Error, initial configuration cannot be solved to match initial Cartesian coordinates, residual",solver.getResidual()
			return None
		print "Warning, initial configuration does not match initial Cartesian coordinates, solving"
		startConfig = robot.getConfig()
	if feasibilityTest is not None and not feasibilityTest(startConfig):
		print "Error: initial configuration is infeasible"
		return None
	if endConfig != None:
		#doing endpoint-constrained cartesian interpolation
		set_cartesian_constraints(b,constraints,solver)
		robot.setConfig(endConfig)
		if not solver.isSolved():
			print "Error, end configuration does not match final Cartesian coordinates, residual",solver.getResidual()
			return None
		if feasibilityTest is not None and not feasibilityTest(startConfig):
			print "Error: final configuration is infeasible"
			return None

	res = RobotTrajectory(robot)
	t = 0
	res.times.append(t)
	res.milestones.append(startConfig)
	qmin0,qmax0 = solver.getJointLimits()
	tol0 = solver.getTolerance()
	solver.setTolerance(tol0*0.1)
	set_cartesian_constraints(a,constraints,solver)
	if not solver.isSolved():
		solver.solve()
		res.times.append(t+1e-7)
		res.milestones.append(robot.getConfig())
		t = res.times[-1]
	paramStallTolerance = 0.01*solver.getTolerance() / config.distance(constraints,a,b)
	stepsize = 0.1
	while t < 1:
		tookstep = False
		tend = min(t+stepsize,1)
		x = config.interpolate(constraints,a,b,tend)
		if endConfig is not None:
			robot.setConfig(robot.interpolate(startConfig,endConfig,tend))
			solver.setBiasConfig(robot.getConfig())
		q = res.milestones[-1]
		solver.setJointLimits([max(vmin,v-delta) for v,vmin in zip(q,qmin0)],[min(vmax,v+delta) for v,vmax in zip(q,qmax0)])
		#print "Trying step",tend-t,"time t=",tend
		if solve_cartesian(x,constraints,solver):
			#valid step, increasing step size
			#print "Accept and increase step"
			tookstep = True
			stepsize *= 1.5
		else:
			#do a line search
			while stepsize > paramStallTolerance:
				stepsize *= 0.5
				tend = min(t+stepsize,1)
				x = config.interpolate(constraints,a,b,tend)
				if endConfig is not None:
					robot.setConfig(robot.interpolate(startConfig,endConfig,tend))
					solver.setBiasConfig(robot.getConfig())
				else:
					robot.setConfig(q)
				#print "Trying step",tend-t,"time t=",tend
				if solve_cartesian(x,constraints,solver):
					#print "Accept"
					tookstep = True
					break
				else:
					solver.setTolerance(tol0)
					if solver.isSolved():
						#print "Grudgingly accepted"
						tookstep = True
						break
					solver.setTolerance(tol0*0.1)
		if not tookstep:
			print "Failed to take a valid step along straight line path at time",res.times[-1],"residual",solver.getResidual()
			#x = config.interpolate(constraints,a,b,res.times[-1])
			#set_cartesian_constraints(x,constraints,solver)
			#robot.setConfig(res.milestones[-1])
			#print "Last residual",solver.getResidual()
			#x = config.interpolate(constraints,a,b,tend)
			#set_cartesian_constraints(x,constraints,solver)
			#print "Residual from last config",solver.getResidual()
			solver.setJointLimits(qmin0,qmax0)
			solver.setTolerance(tol0)
			if maximize:
				return res
			return None
		x = robot.getConfig()
		if feasibilityTest is not None and not feasibilityTest(x):
			print "Infeasibility at time",tend
			solver.setJointLimits(qmin0,qmax0)
			solver.setTolerance(tol0)
			if maximize:
				return res
			return None
		#print "Distances from last:",max(abs(a-b) for (a,b) in zip(res.milestones[-1],x))
		res.times.append(tend)
		res.milestones.append(x)
		t = tend
	solver.setJointLimits(qmin0,qmax0)
	solver.setTolerance(tol0)
	"""
	dist = config.distance(constraints,a,b)
	numDivs = int(math.ceil(dist/delta))
	for j in xrange(numDivs):
		u = float(j+1) / float(numDivs)
		x = config.interpolate(constraints,a,b,u)
		if endConfig is not None:
			robot.setConfig(robot.interpolate(startConfig,endConfig,u))
		if not solve_cartesian(x,constraints,solver):
			print "Failed to solve at time",u
			return None
		#assert solver.isSolved(),"residual "+str(solver.getResidual())
		if feasibilityTest is not None and not feasibilityTest(robot.getConfig()):
			print "Infeasibility at time",u
			return None
		res.times.append(u)
		res.milestones.append(robot.getConfig())
	"""
	#set_cartesian_constraints(b,constraints,solver)
	#robot.setConfig(res.milestones[-1])
	#assert solver.isSolved(),"residual "+str(solver.getResidual())
	return res

class BisectNode:
	def __init__(self,a,b,ua,ub,qa,qb):
		self.a,self.b = a,b
		self.ua,self.ub = ua,ub
		self.qa,self.qb = qa,qb
		self.left,self.right = None,None

def cartesian_interpolate_bisect(robot,a,b,constraints,
	startConfig='robot',endConfig=None,
	delta=1e-2,
	solver=None,
	feasibilityTest=None,
	growthTol=10):
	"""Resolves a continuous robot trajectory that interpolates between two cartesian points
	for a single link of a robot.  Note that the output path is only a kinematic resolution.
	It has time domain [0,1].

	Arguments:
	- robot: the RobotModel or SubRobotModel.
	- a, b: endpoints of the Cartesian trajectory.  Assumed derived from config.getConfig(constraints)
	- constraints: IKObjectives on the link or links that are constrained.  Or, they can be indices, or strings
	  in which case they constrain the transform of the link
	- startConfig: either 'robot' (configuration taken from the robot), a configuration, or None (any configuration)
	- endConfig: same type as startConfig.
	- eps: cartesian error tolerance
	- delta: the maximum configuration-space resolution of the output path
	- solver: None, or a configured IKSolver on the given constraints
	- feasibilityTest: None, or a function f(q) that returns false when a configuration q is infeasible
	- growthTol: the end path can be at most growthTol the length of the length between the start and goal
	  configurations.

	Out: a RobotTrajectory that interpolates the Cartesian path, or None if none can be found
	"""
	assert delta > 0,"Spatial resolution must be positive"
	assert growthTol > 1,"Growth parameter must be in range [1,infty]"
	constraints,startConfig,endConfig,solver = _make_canonical(robot,constraints,startConfig,endConfig,solver)

	assert startConfig != None,"Unable to cartesian bisection interpolate without a start configuration"
	if endConfig == None:
		#find an end point
		robot.setConfig(startConfig)
		if not solve_cartesian(b,constraints,solver):
			print "Error, could not find an end configuration to match final Cartesian coordinates"
			return None
		endConfig = robot.getConfig()
	robot.setConfig(startConfig)
	set_cartesian_constraints(a,constraints,solver)
	if not solver.isSolved():
		if not solver.solve():
			print "Error, initial configuration cannot be solved to match initial Cartesian coordinates, residual",solver.getResidual()
			return None
		print "Warning, initial configuration does not match initial Cartesian coordinates, solving"
		startConfig = robot.getConfig()	
	robot.setConfig(endConfig)
	set_cartesian_constraints(b,constraints,solver)
	if not solver.isSolved():
		if not solver.solve():
			print "Error, final configuration cannot be solved to match final Cartesian coordinates, residual",solver.getResidual()
			return None
		print "Warning, final configuration does not match final Cartesian coordinates, solving"
		endConfig = robot.getConfig()	
	if feasibilityTest is not None and not feasibilityTest(startConfig):
		print "Error: initial configuration is infeasible"
		return None
	if feasibilityTest is not None and not feasibilityTest(endConfig):
		print "Error: final configuration is infeasible"
		return None
	root = BisectNode(a,b,0,1,startConfig,endConfig)
	root.d = robot.distance(startConfig,endConfig)
	dtotal = root.d
	dorig = root.d
	scalecond = 0.5*(2 - 2.0/growthTol)
	q = deque()
	q.append(root)
	while len(q) > 0:
		n = q.pop()
		d0 = n.d
		if d0 <= delta:
			continue
		m = config.interpolate(constraints,n.a,n.b,0.5)
		qm = robot.interpolate(n.qa,n.qb,0.5)
		um = (n.ua+n.ub)*0.5
		robot.setConfig(qm)
		solver.setBiasConfig(qm)
		if not solve_cartesian(m,constraints,solver):
			solver.setBiasConfig([])
			print "Failed to solve at point",um
			return None
		solver.setBiasConfig([])
		d1 = robot.distance(n.qa,qm)
		d2 = robot.distance(qm,n.qb)
		#print d1,d2
		#print qm,"->",robot.getConfig()
		qm = robot.getConfig()
		d1 = robot.distance(n.qa,qm)
		d2 = robot.distance(qm,n.qb)
		dtotal += d1+d2 - d0 
		if dtotal > dorig*growthTol or (d1 > scalecond*d0) or (d2 > scalecond*d0):
			print "Excessive growth condition reached",d0,d1,d2,"at point",um
			print n.qa
			print qm
			print n.qb
			return None
		if feasibilityTest and not feasibilityTest(qm):
			print "Violation of feasibility test","at point",um
			return None
		n.left = BisectNode(n.a,m,n.ua,um,n.qa,qm)
		n.left.d = d1
		n.right = BisectNode(m,n.b,um,n.ub,qm,n.qb)
		n.right.d = d2
		if d1 < d2:
			q.append(n.left)
			q.append(n.right)
		else:
			q.append(n.right)
			q.append(n.left)
	#done resolving, now output path from left to right of tree
	res = RobotTrajectory(robot,[0],[startConfig])
	q = [root]
	while len(q) > 0:
		n = q.pop(-1)
		if n.left is None:
			#leaf node
			res.times.append(n.ub)
			res.milestones.append(n.qb)
		else:
			q.append(n.right)
			q.append(n.left)
	return res

def cartesian_path_interpolate(robot,path,constraints,
	startConfig='robot',endConfig=None,
	delta=1e-2,
	method='any',
	solver=None,
	feasibilityTest=None,
	numSamples=1000,
	maximize=False):
	"""Resolves a continuous robot trajectory that follows a cartesian path for a single
	link of a robot.  Note that the output path is only a kinematic resolution, and may not
	respect the robot's velocity / acceleration limits.

	Arguments:
	- robot: the RobotModel or SubRobotModel.
	- path: a list of milestones, or a Trajectory for the parameters of the given constraints.  In the former
	  case the milestones are spaced 1s apart in time.
	- constraints: IKObjectives on the link or links that are constrained.  Or, they can be indices, or strings
	  in which case they constrain the transform of the link.
	- startConfig: either 'robot' (configuration taken from the robot), a configuration, or None (any configuration)
	- endConfig: same type as startConfig.
	- delta: the maximum configuration-space resolution of the output path
	- method: method used: 'any', 'pointwise', or 'roadmap'.
	- solver: None, or a configured IKSolver on the given constraints
	- feasibilityTest: None, or a function f(q) that returns false when a configuration q is infeasible
	- numSamples: if 'roadmap' or 'any' method is used, the # of configuration space samples that are used.
	- maximize: if not resolved, returns the robot trajectory leading to the furthest point along the path

	Out: a RobotTrajectory that interpolates the Cartesian path, or None if none can be found
	"""
	assert delta > 0,"Spatial resolution must be positive"
	if hasattr(path,'__iter__'):
		path = Trajectory(range(len(path)),path)
	constraints,startConfig,endConfig,solver = _make_canonical(robot,constraints,startConfig,endConfig,solver)
	#correct start and goal configurations, if specified
	if startConfig:
		robot.setConfig(startConfig)
		set_cartesian_constraints(path.milestones[0],constraints,solver)
		if not solver.isSolved():
			if not solver.solve():
				print "Error, initial configuration cannot be solved to match initial Cartesian coordinates"
				return None
			print "Warning, initial configuration does not match initial Cartesian coordinates, solving"
			startConfig = robot.getConfig()	
	if endConfig:
		robot.setConfig(endConfig)
		set_cartesian_constraints(path.milestones[-1],constraints,solver)
		if not solver.isSolved():
			if not solver.solve():
				print "Error, final configuration cannot be solved to match final Cartesian coordinates"
				return None
			print "Warning, final configuration does not match final Cartesian coordinates, solving"
			endConfig = robot.getConfig()	

	#now we're at a canonical setup
	if method == 'any' or method == 'pointwise':
		#try pointwise resolution first
		if startConfig == None:
			if ik.solve_global(constraints,solver.getMaxIters(),solver.getTolerance(),solver.getActiveDofs(),max(100,numSamples),feasibilityTest):
				startConfig = robot.getConfig()
			else:
				print "Error: could not solve for start configuration"
				return None
		res = RobotTrajectory(robot)
		res.times.append(path.times[0])
		res.milestones.append(startConfig)
		infeasible = False
		for i in xrange(len(path.milestones)-1):
			if endConfig is None:
				segEnd = None
			else:
				u = (path.times[i+1] - path.times[i])/(path.times[-1] - path.times[i])
				segEnd = robot.interpolate(res.milestones[-1],endConfig,u)
				robot.setConfig(segEnd)
				if solve_cartesian(path.milestones[i+1],constraints,solver):
					segEnd = robot.getConfig()
			if segEnd is None:
				seg = cartesian_interpolate_linear(robot,path.milestones[i],path.milestones[i+1],constraints,
					startConfig=res.milestones[-1],endConfig=segEnd,delta=delta,solver=solver,feasibilityTest=feasibilityTest)
			else:
				seg = cartesian_interpolate_bisect(robot,path.milestones[i],path.milestones[i+1],constraints,
					startConfig=res.milestones[-1],endConfig=segEnd,delta=delta,solver=solver,feasibilityTest=feasibilityTest)
			if not seg:
				print "Found infeasible cartesian interpolation segment at time",path.times[i+1]
				infeasible = True
				break
			#concatenate
			dt = path.times[i+1] - path.times[i]
			seg.times = [t*dt for t in seg.times]
			res = res.concat(seg,relative=True)
		if not infeasible:
			#print "Resolved with pointwise interpolation!"
			return res
		if method == 'pointwise' and maximize:
			return res
	if method == 'any' or method == 'roadmap':
		#TODO: sample on continuous parameterization of path
		if path.duration() > 0:
			#manual discretization using config.interpolate
			numdivs = 20
			divpts = [path.startTime() + path.duration()*float(i)/(numdivs-1) for i in xrange(numdivs)]
			oldseg = 0
			oldu = 0
			times = [0]
			milestones = [path.milestones[0]]
			for t in divpts:
				s,u = path.getSegment(t)
				if s+1 >= len(path.milestones):
					s = len(path.milestones)-2
					u = 1
				if s == oldseg:
					if u != oldu:
						times.append(t)
						milestones.append(config.interpolate(constraints,path.milestones[s],path.milestones[s+1],u))
				else:
					for i in range(oldseg+1,s+1):
						times.append(path.times[i])
						milestones.append(path.milestones[i])
					times.append(t)
					print s,u
					milestones.append(config.interpolate(constraints,path.milestones[s],path.milestones[s+1],u))
				oldseg,oldu = s,u
			path = path.constructor()(times,milestones)
		import random
		#mark whether we need to sample the end or start
		pathIndices = range(1,len(path.milestones)-1)
		if startConfig == None:
			pathIndices = [0] + pathIndices
		if endConfig == None:
			pathIndices = pathIndices + [len(path.milestones)-1]
		samp = 0
		if startConfig == None:
			#need to seed a start configuration
			while samp < numSamples:
				samp += 1
				solver.sampleInitial()
				if solve_cartesian(path.milestones[0],constraints,solver):
					if feasibilityTest is None or feasibilityTest(robot.getConfig()):
						startConfig = robot.getConfig()
						break
		if endConfig == None:
			#need to seed an end configuration
			samp = 0
			while samp < numSamples:
				samp += 1
				if samp > 0:
					solver.sampleInitial()
				else:
					robot.setConfig(startConfig)
				if solve_cartesian(path.milestones[-1],constraints,solver):
					if feasibilityTest is None or feasibilityTest(robot.getConfig()):
						endConfig = robot.getConfig()
						break
		if startConfig == None or endConfig == None:
			print "Exhausted all samples, perhaps endpoints are unreachable"
			return None
		selfMotionManifolds = [[] for i in path.milestones]
		nodes = []
		configs = []
		ccs = []
		edges = []
		def findpath(depth):
			#start and goal are connected! find a path through the edges list using BFS
			eadj = [[] for n in nodes]
			for (i,j,p) in edges:
				eadj[i].append((j,p))
			q = deque()
			parent = [None]*len(nodes)
			for c in selfMotionManifolds[0]:
				q.append(c)
			print "Adjacency list"
			for i,alist in enumerate(eadj):
				print nodes[i],": ",' '.join(str(nodes[j]) for (j,p) in alist)

			while len(q) > 0:
				n = q.pop()
				for c,p in eadj[n]:
					if parent[c] != None:
						continue
					parent[c] = n
					if nodes[c][0] == depth:
						print "Found a path using roadmap after",samp,"samples"
						#arrived at goal node, trace parent list back
						npath = []
						n = c
						while c != None:
							npath.append(c)
							c = parent[c]
						npath = [n for n in reversed(npath)]
						print ' '.join(str(nodes[n]) for n in npath)
						assert nodes[npath[0]][0] == 0,"Didnt end up at a start configuration?"
						res = RobotTrajectory(robot)
						res.times.append(path.times[0])
						res.milestones.append(configs[npath[0]])
						for i,n in enumerate(npath[:-1]):
							found = False
							for j,p in eadj[n]:
								if j == npath[i+1]:
									print "Suffix",p.times[0],p.times[-1]
									print res.times[0],res.times[-1]
									res = res.concat(p,relative=False)
									print "Resulting range",res.times[0],res.times[-1]
									found = True
									break
							assert found,"Internal error? "+str(nodes[npath[i]])+" -> "+str(nodes[npath[i+1]])
						return res
					q.append(c)
			print "Path to depth",depth,"could not be found"
			return None
		selfMotionManifolds[0].append(0)
		configs.append(startConfig)
		nodes.append((0,0))
		ccs.append(0)
		selfMotionManifolds[-1].append(1)
		configs.append(endConfig)
		nodes.append((len(path.milestones)-1,0))
		ccs.append(1)
		for samp in xrange(samp,numSamples):
			irand = random.choice(pathIndices)
			solver.sampleInitial()
			#check for successful sample on self motion manifold, test feasibility
			if not solve_cartesian(path.milestones[irand],constraints,solver):
				continue
			x = robot.getConfig()
			if feasibilityTest is not None and not feasibilityTest(x):
				continue
			#add to data structure
			nx = len(nodes)
			nodes.append((irand,len(selfMotionManifolds[irand])))
			ccs.append(nx)
			assert len(ccs) == nx+1
			selfMotionManifolds[irand].append(nx)
			configs.append(x)
			#try connecting to other nodes
			k = int(math.log(samp+2)) + 2
			#brute force k-nearest neighbor
			d = []
			for i,n in enumerate(nodes[:-1]):
				if n[0] == irand:
					continue
				dist = config.distance(constraints,path.milestones[n[0]],path.milestones[irand])
				dist = robot.distance(x,configs[i])
				d.append((dist,i))
			k = min(k,len(d))
			print "Sampled at time point",irand,"checking",k,"potential connections"
			totest = [v[1] for v in sorted(d)[:k]]
			for n in totest:
				i = irand
				j = nodes[n][0]
				qi = x
				qj = configs[n]
				ni = nx
				nj = n
				if ccs[ni] == ccs[nj]:
					#same connected component, use visibility graph technique
					continue
				if i > j:
					i,j = j,i
					qi,qj = qj,qi
					ni,nj = nj,ni
				pij = path.constructor()(path.times[i:j+1],path.milestones[i:j+1])
				#try connecting edges
				t = resolve_cartesian_trajectory(robot,pij,constraints,
					startConfig=qi,endConfig=qj,delta=delta,method='pointwise',solver=solver,feasibilityTest=feasibilityTest)
				#t = cartesian_interpolate_bisect(robot,path.milestones[i],path.milestones[j],constraints,qi,qj,delta=delta,solver=solver,feasibilityTest=feasibilityTest)
				if t == None:
					print "  Failed edge",nodes[ni],"->",nodes[nj]
					continue
				#t.times = [path.times[i] + v*(path.times[j]-path.times[i]) for v in t.times]
				print "  Added edge",nodes[ni],"->",nodes[nj]
				edges.append((ni,nj,t))
				if ccs[ni] != ccs[nj]:
					#not in same connected component, collapse ccs
					src,tgt = ccs[ni],ccs[nj]
					if src < tgt: src,tgt = tgt,src
					checkgoal = False
					for i,cc in enumerate(ccs):
						if ccs[i] == src:
							ccs[i] = tgt
							if nodes[i][0] == 0 or nodes[i][0] == len(path.milestones)-1:
								checkgoal=True
					if checkgoal:
						checkgoal = False
						for c in selfMotionManifolds[0]:
							for d in selfMotionManifolds[-1]:
								if ccs[c] == ccs[d]:
									checkgoal = True
									break
							if checkgoal:
								break
					if checkgoal:
						return findpath(len(path.milestones)-1)
			if ccs[-1] != 0 and ccs[-1] != 1 and False:
				#didn't connect to either start or goal... delete isolated points?
				print "Isolated node, removing..."
				edges = [(i,j,t) for (i,j,t) in edges if i != nx and j == nx]
				selfMotionManifolds[irand].pop(-1)
				nodes.pop(-1)
				configs.pop(-1)
				ccs.pop(-1)
			#raw_input()
		if maximize:
			#find the point furthest along the path
			startccs = set()
			for c in selfMotionManifolds[0]:
				startccs.add(ccs[c])
			maxdepth = 0
			maxnode = 0
			for i,cc in enumerate(ccs):
				if nodes[i][0] > maxdepth and cc in startccs:
					maxdepth = nodes[i][0]
					maxnode = i
			print "Connected components:"
			for n,cc in zip(nodes,ccs):
				print "  ",n,":",cc
			print "Got to depth",maxdepth
			return findpath(maxdepth)
		print "Unable to find a feasible path within",numSamples,"iterations"
		print "Number of feasible samples per time instance:"
		return None
	return None


