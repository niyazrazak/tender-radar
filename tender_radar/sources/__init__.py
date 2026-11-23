from tender_radar.sources.etimad import EtimadSource
from tender_radar.sources.monaqasat import MonaqasatSource
from tender_radar.sources.oman_tender_board import OmanTenderBoardSource

# Add new portals here (Kuwait, Bahrain, QatarEnergy, ...).
SOURCES = {source.name: source for source in (MonaqasatSource, EtimadSource, OmanTenderBoardSource)}
