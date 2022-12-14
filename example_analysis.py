## Needs to have ROOT.TG4Event loaded to work
import ROOT
from ROOT import TLorentzVector
from math import sqrt
import sys
from glob import glob

## Make ROOT non-hideous
ROOT.gROOT.SetBatch(1)
ROOT.gStyle.SetLineWidth(3)
ROOT.gStyle.SetOptStat(0)
ROOT.gStyle.SetOptTitle(0)
ROOT.TGaxis.SetMaxDigits(3)

ROOT.gStyle.SetTextSize(0.06)
ROOT.gStyle.SetLabelSize(0.05,"xyzt")
ROOT.gStyle.SetTitleSize(0.06,"xyzt")

ROOT.gStyle.SetPadTickX(1)
ROOT.gStyle.SetPadTickY(1)
ROOT.gStyle.SetNdivisions(505, "XY")

ROOT.gStyle.SetPalette(ROOT.kInvertedDarkBodyRadiator)
ROOT.gStyle.SetNumberContours(255)

## Just some nicer colours
## From: https://personal.sron.nl/~pault/#sec:qualitative
kkBlue    = ROOT.TColor(9000,   0/255., 119/255., 187/255.)
kkCyan    = ROOT.TColor(9001,  51/255., 187/255., 238/255.)
kkTeal    = ROOT.TColor(9002,   0/255., 153/255., 136/255.)
kkOrange  = ROOT.TColor(9003, 238/255., 119/255.,  51/255.)
kkRed     = ROOT.TColor(9004, 204/255.,  51/255.,  17/255.)
kkMagenta = ROOT.TColor(9005, 238/255.,  51/255., 119/255.)
kkGray    = ROOT.TColor(9006, 187/255., 187/255., 187/255.)

## Pop up a canvas
can = ROOT.TCanvas("can", "can", 1000, 800)
can .cd()

## Is the position within the 2x2 active volume?
def is_2x2_contained(pos):
    if abs(pos[0]) > 670: return False
    if abs(pos[1] - 430) > 670: return False
    if abs(pos[2]) > 670: return False
    return True

## We want to ignore all hits produced by neutrons or their daughters
## So, make a set of all true trajectories that are neutrons or their descendants 
def get_neutron_and_daughter_ids(event):
    
    neutrons  = set()
    daughters = set()
    
    for traj in event.Trajectories:
        
        if traj.GetPDGCode() == 2112:
            neutrons .add(traj.GetTrackId())
            continue
        par_id = traj.GetParentId()
        if par_id in neutrons or par_id in daughters:
            daughters .add(traj.GetTrackId())

    return neutrons.union(daughters)


## Get a set of trajectory IDs with total energy < 10 MeV
## This is a semi-arbitrary cut-off to ignore delta rays and
## other low-energy stuff that leaks out of the detector
def get_low_energy_ids(event):
    return set(x.GetTrackId() for x in event.Trajectories if x.GetInitialMomentum().E() < 10)


## This is an extremely simple signal selection
## Simply require a final state muon
def is_ccinc(pdg_list):
    if 13 in pdg_list or -13 in pdg_list:
        return True
    return False


## Find the ids of primary particles with a given PDG
def get_traj_ids_for_pdg(particles, pdgs):

    ## Loop over the truth trajectories
    ## Keep track of track ids if the PDG code is the one we desire
    return tuple(x.GetTrackId() for x in particles if x.GetPDGCode() in pdgs)


## Get the PrimaryParticles of a specific type
def get_traj_for_pdg(particles, pdgs):
    return tuple(x for x in particles if x.GetPDGCode() in pdgs)

## Determine if the muon in an event is "tagged"
## As they very rarely are contained, here we look for muons that punch through and exit downstream of MINERvA
## (Other particles almost never make it through at our energies
def is_muon_tagged(event):
    
    ## Get the primary muon ID (muons require special treatment)
    muon_id = get_traj_ids_for_pdg(event.Primaries[0].Particles, [13, -13])

    ## If there isn't a muon... this isn't CC, so default to True
    ## (because who cares where the outgoing neutrino goes in an NC event)
    if len(muon_id)==0: return True

    ## MINERvA's maximum z value (mm)
    ## This is very geometry specific
    z_max = 3500

    ## Radius of a cylinder that approximates MINERvA
    ## (this is slightly smaller than a cylinder that would go through the "tips" of the MINERvA hexagon)
    approx_rad = 1870
    
    high_z = 0
    
    ## Loop over the detector segments (see description elsewhere in this file)
    for seg in event.SegmentDetectors:
        
        ## Loop over the segments in the volume
        nChunks = len(seg[1])
        for n in range(nChunks):
            
            ## Get the primary id that is associated with this segment
            par_contrib = seg[1][n].GetPrimaryId()

            ## Only consider contributions that can be tracked back to muons
            if par_contrib not in muon_id: continue

            pos = seg[1][n].GetStop()

            ## !!! This is a very coarse approximation !!!
            ## Contained muons must leave hits (in air) that exceed the z-maximum of MINERvA
            if pos[2] > z_max:
                high_z += 1
                continue
            
            ## They must also not exit out the side of MINERvA
            ## Here MINERvA is very crudely approximated with a cylinder
            ## If sqrt(x^2 + y*2) > the radius of that cylinder before the muon exits out the back, it's not tagged
            ## (Take into account the fact the detector is shifted up 430 mm in y)
            if sqrt(pos[0]*pos[0] + (pos[1]-430)*(pos[1]-430)) > approx_rad: return False

    ## Check that the muon went past MINERvA
    if not high_z: return False

    ## Looks like the muon was "tagged"!
    return True


## Determine if the hadronic side of an event is contained ***in the 2x2***
## Some assumptions here
def is_hadronic_contained(event):

    ## Get all neutrons and neutron descendents in the event
    neutron_ids = get_neutron_and_daughter_ids(event)
    
    ## Get a list of low energy truth trajectories (may be quite long)
    low_energy_ids = get_low_energy_ids(event)

    ## Get the primary muon id
    muon_ids = get_traj_ids_for_pdg(event.Primaries[0].Particles, [13, -13])

    ## Loop over the detector segments (this is rather a complex object...)
    for seg in event.SegmentDetectors:
        
        ## seg[0] is the detector volume (named according to the gdml file tag)
        ## seg[1] is an array of segments in the volume
        ## Note that the loop is over the detectors, not over the particles 
        
        ## Loop over the segments in the volume
        nChunks = len(seg[1])
        for n in range(nChunks):
            
            ## Get the truth trajectory ID that is the primary contributor to this segment
            ## (Multiple particles can deposit energy at the same point in space, hence the ambiguity)
            key_contrib = seg[1][n].GetContributors()[0]
            par_contrib = seg[1][n].GetPrimaryId()

            ## Take muons out at this stage (they have to be treated differently)
            if par_contrib in muon_ids: continue
            
            ## Did this segment come (mostly) from a neutron or a descendant from a neutron?
            if key_contrib in neutron_ids: continue
            
            ## Skip anything which is very low energy (delta rays often escape the volume and distort the containment numbers)
            if key_contrib in low_energy_ids: continue
            
            ## See if this is outside my "contained" box
            pos = seg[1][n].GetStop()

            ## As soon as we find something uncontained, we can just leave
            if not is_2x2_contained(pos): return False

    ## If not, the event is contained!
    return True


## Determine if the event is contained
def is_event_contained(event):
    if not is_muon_tagged(event):
        return False
    if not is_hadronic_contained(event):
        return False
    return True

## Return the reconstructed energy for a single PRIMARY particle
def get_reco_energy(event, traj_id):

    reco_energy = 0
    
    ## Loop over the detector segments
    for seg in event.SegmentDetectors:
        
        ## Loop over the segments in the volume
        nChunks = len(seg[1])
        for n in range(nChunks):
            
            ## Get the primary truth trajectory ID that corresponds to this segment
            prim_id = seg[1][n].GetPrimaryId()
            
            ## Did this segment come from the particle of interest?
            if prim_id != traj_id: continue
            
            reco_energy += seg[1][n].GetEnergyDeposit()

    return reco_energy


## Return the neutrino 4 momentum
## Note that this is only in the pass-through GENIE info, so uses a different tree
## (But that tree has the same number of entries)
def get_neutrino_4mom(groo_event):

    ## Loop over the particles in GENIE's stack
    for p in range(groo_event.StdHepN):

        ## Look for the particle status
        ## 0 is initial state, 1 is final, check the GENIE docs for others
        if groo_event.StdHepStatus[p] != 0: continue

        ## Check for a neutrino (any flavor)
        if abs(groo_event.StdHepPdg[p]) not in [12, 14, 16]: continue

        ## Kindly redirect any complaints about this line to /dev/null
        ## edep-sim uses MeV, gRooTracker uses GeV...
        return TLorentzVector(groo_event.StdHepP4[p*4 + 0]*1000,
                              groo_event.StdHepP4[p*4 + 1]*1000,
                              groo_event.StdHepP4[p*4 + 2]*1000,
                              groo_event.StdHepP4[p*4 + 3]*1000)
    ## Should never happen...
    return None
        
## Example event loop
def test_containment(infilelist):

    ## Get the file(s)
    edep_tree = ROOT.TChain("EDepSimEvents")
    groo_tree = ROOT.TChain("DetSimPassThru/gRooTracker")

    ## Loop over the file list and add them to the chain
    for file in infilelist:
        ## Allow for escaped wildcards in the input...
        for f in glob(file):
            edep_tree.Add(f)
            groo_tree.Add(f)

    nevts  = edep_tree.GetEntries()
    
    ## Set up histograms
    q2_all = ROOT.TH1D("q2_all",
                       "q2_all;Q^{2} (GeV); N. events",
                       25, 0, 5)
    
    q2_cont = ROOT.TH1D("q2_cont",
                        "q2_cont;Q^{2} (GeV); Containment fraction",
                        25, 0, 5)

    pi_energy_smearing = ROOT.TH2D("pi_energy_smearing",
                                   "pi_energy_smearing;p_{#pi}^{true} (GeV); p_{#pi}^{reco} (GeV); N. events",
                                   20, 0, 0.5, 20, 0, 0.5)
    
    ## Loop over events
    print("Looping over", nevts, "events")
    for evt in range(nevts):

        if evt%(int(nevts/10)) == 0 and evt != 0: print("Processed event:", evt)
        
        edep_tree.GetEntry(evt)
        groo_tree.GetEntry(evt)
        
        ## Vertex info
        ## Note the assumption that there's one vertex/event here
        ## This won't be true for full spill simulation!
        vertex = edep_tree.Event.Primaries[0]

        ## Get the list of pdgs in this event (can be used to classify the topology)
        prim_pdg_list = tuple(x.GetPDGCode() for x in vertex.Particles)

        ## Is this event "signal"? If not, skip it
        if not is_ccinc(prim_pdg_list): continue

        ## Is this event contained?
        cont = is_event_contained(edep_tree.Event)

        ## Get the neutrino info from the gRooTracker tree
        nu_4mom = get_neutrino_4mom(groo_tree)

        ## Check the neutrino exists... if not, something very funky has happened
        if not nu_4mom:
            print("Something very funky has happened!")
            continue

        ## Get the muon info
        muon_trajs = get_traj_for_pdg(vertex.Particles, [13, -13])

        ## Check the muon exists (for this CC-INC event)... if not, something else very funky has happened
        if len(muon_trajs) == 0:
            print("Something else very funky has happened!")
            continue            

        mu_4mom = muon_trajs[0].GetMomentum()

        ## Calculate true Q2 (in GeV)
        q2 = -1 *(mu_4mom - nu_4mom).Mag2()/1e6

        ## Keep track of the Q2 for all events
        q2_all .Fill(q2)
        
        ## Only continue with contained events
        if not cont: continue

        ## Keep track of the Q2 for contained events
        q2_cont .Fill(q2)
        
        ## Now, look at the energy reconstruction for all charged pion from contained events
        ## (randomly picked as an example)
        primary_pion_trajs = get_traj_for_pdg(vertex.Particles, [211, -211])

        ## Loop over all primary pions
        for pion in primary_pion_trajs:

            ## Calculate the kinetic energy of the pion
            true_4mom = pion.GetMomentum()
            true_e = true_4mom.E() - true_4mom.M()

            ## Calculate the energy deposited
            reco_e = get_reco_energy(edep_tree.Event, pion.GetTrackId())

            pi_energy_smearing.Fill(true_e/1000, reco_e/1000)

    ## Calculate the containment efficiency
    q2_cont.Divide(q2_all)
    
    ## Make some pretty plots
    can.cd()
    q2_all .Draw()
    q2_all .SetMinimum(0)
    q2_all .SetLineColor(9000)
    q2_all .SetLineWidth(3)
    ROOT.gPad.SetRightMargin(0.02)
    ROOT.gPad.SetTopMargin(0.07)
    ROOT.gPad.SetLeftMargin(0.15)
    ROOT.gPad.SetBottomMargin(0.14)
    ROOT.gPad.RedrawAxis()
    ROOT.gPad.Update()
    can .SaveAs("plots/example_ccinc_q2.png")
    
    q2_cont .Draw()
    q2_cont .SetLineWidth(3)
    q2_cont .SetMinimum(0)
    q2_cont .SetLineColor(9000)
    ROOT.gPad.SetTopMargin(0.02)
    ROOT.gPad.Update()
    can .SaveAs("plots/example_ccinc_q2_2x2cont.png")
    
    pi_energy_smearing.Draw("COLZ")
    pi_energy_smearing.GetZaxis().RotateTitle(1)
    ROOT.gPad.SetRightMargin(0.18)
    ROOT.gPad.RedrawAxis()
    ROOT.gPad.Update()
    can .SaveAs("plots/example_pi_erec_2x2cont.png")
    
    return

if __name__ == '__main__':

    if len(sys.argv) < 2:
        print("At least one edep-sim processed file is required as an argument!")
        sys.exit()

    file_list = [sys.argv[x] for x in range(1, len(sys.argv))]
    test_containment(file_list)
