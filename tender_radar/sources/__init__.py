from tender_radar.sources.etimad import EtimadSource
from tender_radar.sources.monaqasat import MonaqasatSource
from tender_radar.sources.mwani import MwaniSource
from tender_radar.sources.oman_tender_board import OmanTenderBoardSource
from tender_radar.sources.qfa import QfaSource

# Add new portals here (Kuwait, Bahrain, ...).
SOURCES = {
    source.name: source
    for source in (MonaqasatSource, MwaniSource, QfaSource, EtimadSource, OmanTenderBoardSource)
}
