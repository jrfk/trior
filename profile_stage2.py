import sys,cProfile,pstats,trio
sys.path.insert(0,'benchmarks')
from trio_rust_poc import activate
from workloads import execute
activate(sys.argv[1])
p=cProfile.Profile(); p.enable()
trio.run(execute,'checkpoint_600',{'tasks':600,'steps':100})
p.disable();p.dump_stats('results/stage2/profile-'+sys.argv[1]+'.pstats')
pstats.Stats(p).sort_stats('tottime').print_stats(25)
