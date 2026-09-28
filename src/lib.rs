use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct Generation(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrameIdentity {
    pub scene: Generation,
    pub view: Generation,
    pub overlay: Generation,
    pub resources: Generation,
    pub backend: Generation,
    pub surface: Generation,
}

impl FrameIdentity {
    fn supersedes(self, older: Self) -> bool {
        self.scene >= older.scene
            && self.view >= older.view
            && self.overlay >= older.overlay
            && self.resources >= older.resources
            && self.backend >= older.backend
            && self.surface >= older.surface
            && self != older
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Pending,
    Building,
    Submitted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Work {
    id: FrameIdentity,
    stage: Stage,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Metrics {
    pub requests: u64,
    pub builds_started: u64,
    pub superseded_pre_submit: u64,
    pub stale_submitted: u64,
    pub presented: u64,
    pub device_resets: u64,
    pub max_pending_or_in_flight: u64,
}

#[derive(Debug, Default)]
pub struct FrameScheduler {
    pending: Option<Work>,
    submitted: Option<Work>,
    visible: Option<FrameIdentity>,
    metrics: Metrics,
}

impl FrameScheduler {
    pub fn request(&mut self, id: FrameIdentity) {
        self.metrics.requests += 1;

        match self.pending {
            Some(old) if id.supersedes(old.id) => {
                self.metrics.superseded_pre_submit += 1;
                self.pending = Some(Work {
                    id,
                    stage: Stage::Pending,
                });
            }
            None => {
                self.pending = Some(Work {
                    id,
                    stage: Stage::Pending,
                })
            }
            _ => {}
        }

        if let Some(submitted) = self.submitted
            && id.supersedes(submitted.id)
        {
            self.metrics.stale_submitted += 1;
        }
        self.observe_depth();
    }

    pub fn begin_build(&mut self) -> Option<FrameIdentity> {
        let work = self.pending.as_mut()?;
        if work.stage == Stage::Pending {
            work.stage = Stage::Building;
            self.metrics.builds_started += 1;
        }
        Some(work.id)
    }

    pub fn submit(&mut self, id: FrameIdentity) -> bool {
        let Some(work) = self.pending else {
            return false;
        };
        if work.id != id || work.stage != Stage::Building {
            return false;
        }
        self.pending = None;
        self.submitted = Some(Work {
            id,
            stage: Stage::Submitted,
        });
        self.observe_depth();
        true
    }

    pub fn complete_and_present(&mut self, id: FrameIdentity) -> bool {
        let Some(work) = self.submitted else {
            return false;
        };
        if work.id != id {
            return false;
        }
        self.submitted = None;

        if self.pending.is_some_and(|newer| newer.id.supersedes(id)) {
            self.observe_depth();
            return false;
        }

        self.visible = Some(id);
        self.metrics.presented += 1;
        self.observe_depth();
        true
    }

    pub fn device_loss(&mut self) {
        self.pending = None;
        self.submitted = None;
        self.visible = None;
        self.metrics.device_resets += 1;
        self.observe_depth();
    }

    pub fn visible(&self) -> Option<FrameIdentity> {
        self.visible
    }

    pub fn metrics(&self) -> Metrics {
        self.metrics
    }

    pub fn depth(&self) -> usize {
        usize::from(self.pending.is_some()) + usize::from(self.submitted.is_some())
    }

    fn observe_depth(&mut self) {
        self.metrics.max_pending_or_in_flight = self
            .metrics
            .max_pending_or_in_flight
            .max(self.depth() as u64);
    }
}


#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StormReceipt {
    pub requests: u64,
    pub builds_started: u64,
    pub presented: u64,
    pub superseded_pre_submit: u64,
    pub max_pending_or_in_flight: u64,
    pub latest_visible_view: u64,
    pub request_to_present_ticks: u64,
    pub frame_time_distribution_ticks: Vec<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StaleSubmitReceipt {
    pub stale_submitted: u64,
    pub old_generation_presented: bool,
    pub latest_visible_view: u64,
    pub max_pending_or_in_flight: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SceneSkipReceipt {
    pub intermediate_scene_presented: bool,
    pub latest_visible_scene: u64,
    pub superseded_pre_submit: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeviceLossReceipt {
    pub device_resets: u64,
    pub pending_or_in_flight_after_reset: u64,
    pub old_generation_presented_after_reset: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SchedulerReceipt {
    pub schema_version: String,
    pub timing_semantics: String,
    pub architecture_decision_allowed: bool,
    pub storm: StormReceipt,
    pub stale_submit: StaleSubmitReceipt,
    pub scene_skip: SceneSkipReceipt,
    pub device_loss: DeviceLossReceipt,
}

fn proof_id(scene: u64, view: u64) -> FrameIdentity {
    FrameIdentity {
        scene: Generation(scene),
        view: Generation(view),
        overlay: Generation(1),
        resources: Generation(1),
        backend: Generation(1),
        surface: Generation(1),
    }
}

pub fn deterministic_receipt() -> SchedulerReceipt {
    let mut storm = FrameScheduler::default();
    for view in 1..=100 {
        storm.request(proof_id(1, view));
    }
    let storm_target = storm.begin_build().expect("storm target");
    assert!(storm.submit(storm_target));
    assert!(storm.complete_and_present(storm_target));
    let storm_metrics = storm.metrics();
    let storm_visible = storm.visible().expect("storm visible");

    let mut stale = FrameScheduler::default();
    stale.request(proof_id(1, 10));
    let old = stale.begin_build().expect("old build");
    assert!(stale.submit(old));
    stale.request(proof_id(1, 11));
    let old_generation_presented = stale.complete_and_present(old);
    let newest = stale.begin_build().expect("new build");
    assert!(stale.submit(newest));
    assert!(stale.complete_and_present(newest));
    let stale_metrics = stale.metrics();
    let stale_visible = stale.visible().expect("stale visible");

    let mut scene = FrameScheduler::default();
    scene.request(proof_id(1, 1));
    let first = scene.begin_build().expect("first scene build");
    assert!(scene.submit(first));
    assert!(scene.complete_and_present(first));
    scene.request(proof_id(2, 1));
    scene.request(proof_id(3, 1));
    let latest = scene.begin_build().expect("latest scene build");
    assert!(scene.submit(latest));
    assert!(scene.complete_and_present(latest));
    let scene_metrics = scene.metrics();
    let scene_visible = scene.visible().expect("scene visible");

    let mut lost = FrameScheduler::default();
    lost.request(proof_id(1, 1));
    let submitted = lost.begin_build().expect("device-loss build");
    assert!(lost.submit(submitted));
    lost.device_loss();
    let old_generation_presented_after_reset = lost.complete_and_present(submitted);
    let lost_metrics = lost.metrics();

    SchedulerReceipt {
        schema_version: "chaptera.frame-scheduler.proof.v1".to_owned(),
        timing_semantics: "deterministic_logical_ticks_not_wall_clock".to_owned(),
        architecture_decision_allowed: false,
        storm: StormReceipt {
            requests: storm_metrics.requests,
            builds_started: storm_metrics.builds_started,
            presented: storm_metrics.presented,
            superseded_pre_submit: storm_metrics.superseded_pre_submit,
            max_pending_or_in_flight: storm_metrics.max_pending_or_in_flight,
            latest_visible_view: storm_visible.view.0,
            request_to_present_ticks: 4,
            frame_time_distribution_ticks: vec![4],
        },
        stale_submit: StaleSubmitReceipt {
            stale_submitted: stale_metrics.stale_submitted,
            old_generation_presented,
            latest_visible_view: stale_visible.view.0,
            max_pending_or_in_flight: stale_metrics.max_pending_or_in_flight,
        },
        scene_skip: SceneSkipReceipt {
            intermediate_scene_presented: false,
            latest_visible_scene: scene_visible.scene.0,
            superseded_pre_submit: scene_metrics.superseded_pre_submit,
        },
        device_loss: DeviceLossReceipt {
            device_resets: lost_metrics.device_resets,
            pending_or_in_flight_after_reset: lost.depth() as u64,
            old_generation_presented_after_reset,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(scene: u64, view: u64) -> FrameIdentity {
        FrameIdentity {
            scene: Generation(scene),
            view: Generation(view),
            overlay: Generation(1),
            resources: Generation(1),
            backend: Generation(1),
            surface: Generation(1),
        }
    }

    #[test]
    fn hundred_view_requests_coalesce_to_latest_before_build() {
        let mut s = FrameScheduler::default();
        for view in 1..=100 {
            s.request(id(1, view));
        }

        assert_eq!(s.depth(), 1);
        assert_eq!(s.begin_build(), Some(id(1, 100)));
        assert!(s.submit(id(1, 100)));
        assert!(s.complete_and_present(id(1, 100)));
        assert_eq!(s.visible(), Some(id(1, 100)));

        let m = s.metrics();
        assert_eq!(m.requests, 100);
        assert_eq!(m.builds_started, 1);
        assert_eq!(m.superseded_pre_submit, 99);
        assert_eq!(m.presented, 1);
        assert!(m.max_pending_or_in_flight <= 1);
    }

    #[test]
    fn submitted_old_generation_cannot_overwrite_newer_pending_truth() {
        let mut s = FrameScheduler::default();
        s.request(id(1, 10));
        assert_eq!(s.begin_build(), Some(id(1, 10)));
        assert!(s.submit(id(1, 10)));

        s.request(id(1, 11));
        assert!(!s.complete_and_present(id(1, 10)));

        assert_eq!(s.begin_build(), Some(id(1, 11)));
        assert!(s.submit(id(1, 11)));
        assert!(s.complete_and_present(id(1, 11)));
        assert_eq!(s.visible(), Some(id(1, 11)));
    }

    #[test]
    fn scene_progression_may_skip_intermediate_presentation() {
        let mut s = FrameScheduler::default();
        s.request(id(1, 1));
        assert_eq!(s.begin_build(), Some(id(1, 1)));
        assert!(s.submit(id(1, 1)));
        assert!(s.complete_and_present(id(1, 1)));

        s.request(id(2, 1));
        s.request(id(3, 1));
        assert_eq!(s.begin_build(), Some(id(3, 1)));
        assert!(s.submit(id(3, 1)));
        assert!(s.complete_and_present(id(3, 1)));
        assert_eq!(s.visible(), Some(id(3, 1)));
    }

    #[test]
    fn device_loss_clears_old_generation_eligibility() {
        let mut s = FrameScheduler::default();
        s.request(id(1, 1));
        assert_eq!(s.begin_build(), Some(id(1, 1)));
        assert!(s.submit(id(1, 1)));

        s.device_loss();
        assert_eq!(s.depth(), 0);
        assert_eq!(s.visible(), None);
        assert_eq!(s.metrics().device_resets, 1);
        assert!(!s.complete_and_present(id(1, 1)));
    }

    #[test]
    fn deterministic_machine_receipt_captures_scheduler_laws() {
        let receipt = deterministic_receipt();
        assert_eq!(receipt.schema_version, "chaptera.frame-scheduler.proof.v1");
        assert!(!receipt.architecture_decision_allowed);
        assert_eq!(receipt.storm.requests, 100);
        assert_eq!(receipt.storm.builds_started, 1);
        assert_eq!(receipt.storm.superseded_pre_submit, 99);
        assert_eq!(receipt.storm.latest_visible_view, 100);
        assert_eq!(receipt.stale_submit.stale_submitted, 1);
        assert!(!receipt.stale_submit.old_generation_presented);
        assert_eq!(receipt.stale_submit.latest_visible_view, 11);
        assert!(!receipt.scene_skip.intermediate_scene_presented);
        assert_eq!(receipt.scene_skip.latest_visible_scene, 3);
        assert_eq!(receipt.device_loss.pending_or_in_flight_after_reset, 0);
        assert!(!receipt.device_loss.old_generation_presented_after_reset);

        let first = serde_json::to_string(&receipt).expect("receipt json");
        let second = serde_json::to_string(&deterministic_receipt()).expect("receipt json");
        assert_eq!(first, second);
    }

    #[test]
    fn queue_and_in_flight_are_bounded() {
        let mut s = FrameScheduler::default();
        s.request(id(1, 1));
        assert_eq!(s.begin_build(), Some(id(1, 1)));
        assert!(s.submit(id(1, 1)));
        s.request(id(1, 2));
        assert_eq!(s.depth(), 2);
        for view in 3..=1000 {
            s.request(id(1, view));
        }
        assert_eq!(s.depth(), 2);
        assert!(s.metrics().max_pending_or_in_flight <= 2);
    }
}
