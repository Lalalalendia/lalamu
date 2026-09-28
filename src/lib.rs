use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Scenario {
    OpenParse,
    MoveNode,
    SmallStoryEdit,
    GeometryOnlyReflow,
    ReplaceImageExport,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CopyClass {
    InternalCopy,
    HistoryRetention,
    RequiredFinalSerialization,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Site {
    OpenParseInput,
    OpenParseContents,
    OpenParseQuill,
    OpenParseEscher,
    RevisionExecutorDetach,
    RevisionHistorySnapshot,
    LayoutPreparedUnitsClone,
    ReplaceImageAssetClone,
    FinalSerialization,
}

#[derive(Debug, Default)]
pub struct CopyLedger {
    counters: [AtomicU64; 9],
}

impl CopyLedger {
    pub const fn new() -> Self {
        Self {
            counters: [
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
                AtomicU64::new(0),
            ],
        }
    }

    pub fn add_bytes(&self, site: Site, bytes: u64) {
        self.counters[site as usize].fetch_add(bytes, Ordering::Relaxed);
    }

    pub fn snapshot(&self, scenario: Scenario) -> Receipt {
        let events = ALL_SITES
            .iter()
            .filter_map(|site| {
                let bytes = self.counters[*site as usize].load(Ordering::Relaxed);
                (bytes > 0).then_some(Event {
                    site: *site,
                    class: class_for(*site),
                    bytes,
                })
            })
            .collect();

        Receipt {
            schema: "chaptera.copy-ledger.proof.v1".to_owned(),
            scenario,
            events,
        }
    }
}

const ALL_SITES: [Site; 9] = [
    Site::OpenParseInput,
    Site::OpenParseContents,
    Site::OpenParseQuill,
    Site::OpenParseEscher,
    Site::RevisionExecutorDetach,
    Site::RevisionHistorySnapshot,
    Site::LayoutPreparedUnitsClone,
    Site::ReplaceImageAssetClone,
    Site::FinalSerialization,
];

fn class_for(site: Site) -> CopyClass {
    match site {
        Site::RevisionHistorySnapshot => CopyClass::HistoryRetention,
        Site::FinalSerialization => CopyClass::RequiredFinalSerialization,
        _ => CopyClass::InternalCopy,
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Event {
    pub site: Site,
    pub class: CopyClass,
    pub bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Receipt {
    pub schema: String,
    pub scenario: Scenario,
    pub events: Vec<Event>,
}

pub fn run_source_free_scenario(scenario: Scenario) -> Receipt {
    let ledger = CopyLedger::new();

    match scenario {
        Scenario::OpenParse => {
            ledger.add_bytes(Site::OpenParseInput, 4096);
            ledger.add_bytes(Site::OpenParseContents, 2048);
            ledger.add_bytes(Site::OpenParseQuill, 1024);
            ledger.add_bytes(Site::OpenParseEscher, 512);
        }
        Scenario::MoveNode => {
            ledger.add_bytes(Site::RevisionExecutorDetach, 8192);
            ledger.add_bytes(Site::RevisionHistorySnapshot, 8192);
        }
        Scenario::SmallStoryEdit => {
            ledger.add_bytes(Site::RevisionExecutorDetach, 8192);
            ledger.add_bytes(Site::RevisionHistorySnapshot, 8192);
        }
        Scenario::GeometryOnlyReflow => {
            ledger.add_bytes(Site::LayoutPreparedUnitsClone, 3200);
        }
        Scenario::ReplaceImageExport => {
            ledger.add_bytes(Site::ReplaceImageAssetClone, 16384);
            ledger.add_bytes(Site::FinalSerialization, 32768);
        }
    }

    ledger.snapshot(scenario)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_five_scenarios_are_deterministic() {
        let scenarios = [
            Scenario::OpenParse,
            Scenario::MoveNode,
            Scenario::SmallStoryEdit,
            Scenario::GeometryOnlyReflow,
            Scenario::ReplaceImageExport,
        ];

        for scenario in scenarios {
            let a = serde_json::to_string(&run_source_free_scenario(scenario)).unwrap();
            let b = serde_json::to_string(&run_source_free_scenario(scenario)).unwrap();
            assert_eq!(a, b);
        }
    }

    #[test]
    fn unrelated_sites_remain_zero_and_absent() {
        let receipt = run_source_free_scenario(Scenario::GeometryOnlyReflow);
        assert_eq!(receipt.events.len(), 1);
        assert_eq!(receipt.events[0].site, Site::LayoutPreparedUnitsClone);
        assert_eq!(receipt.events[0].bytes, 3200);
    }

    #[test]
    fn required_serialization_is_not_counted_as_internal_copy() {
        let receipt = run_source_free_scenario(Scenario::ReplaceImageExport);
        let final_event = receipt
            .events
            .iter()
            .find(|event| event.site == Site::FinalSerialization)
            .unwrap();
        assert_eq!(final_event.class, CopyClass::RequiredFinalSerialization);

        let clone_event = receipt
            .events
            .iter()
            .find(|event| event.site == Site::ReplaceImageAssetClone)
            .unwrap();
        assert_eq!(clone_event.class, CopyClass::InternalCopy);
    }

    #[test]
    fn history_retention_is_separate_from_transient_detach() {
        let receipt = run_source_free_scenario(Scenario::MoveNode);
        assert!(receipt.events.iter().any(|event| {
            event.site == Site::RevisionExecutorDetach && event.class == CopyClass::InternalCopy
        }));
        assert!(receipt.events.iter().any(|event| {
            event.site == Site::RevisionHistorySnapshot
                && event.class == CopyClass::HistoryRetention
        }));
    }

    #[test]
    fn counter_api_accumulates_without_event_objects() {
        let ledger = CopyLedger::new();
        ledger.add_bytes(Site::OpenParseQuill, 10);
        ledger.add_bytes(Site::OpenParseQuill, 20);
        let receipt = ledger.snapshot(Scenario::OpenParse);
        assert_eq!(receipt.events.len(), 1);
        assert_eq!(receipt.events[0].bytes, 30);
    }
}
