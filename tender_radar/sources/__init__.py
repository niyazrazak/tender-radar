from tender_radar.sources.bahrain_tender_board import BahrainTenderBoardSource
from tender_radar.sources.etimad import EtimadSource
from tender_radar.sources.kuwait_capt import KuwaitCaptSource
from tender_radar.sources.monaqasat import MonaqasatSource
from tender_radar.sources.mwani import MwaniSource
from tender_radar.sources.oman_tender_board import OmanTenderBoardSource
from tender_radar.sources.qfa import QfaSource
from tender_radar.sources.sidra import SidraSource
from tender_radar.sources.woqod import WoqodSource

# Add new portals here (UAE, ...).
SOURCES = {
    source.name: source
    for source in (
        MonaqasatSource, MwaniSource, QfaSource, SidraSource, WoqodSource, EtimadSource, OmanTenderBoardSource,
        KuwaitCaptSource, BahrainTenderBoardSource,
    )
}
