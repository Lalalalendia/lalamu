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
                self.pending = Some(Work { id, stage: Stage::Pending });
            }
            None => self.pending = Some(Work { id, stage: Stage::Pending }),
            _ => {}
        }

        if let Some(submitted) = self.submitted {
            if id.supersedes(submitted.id) {
                self.metrics.stale_submitted += 1;
            }
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
        self.submitted = Some(Work { id, stage: Stage::Submitted });
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

    pub fn device_loss(&mut self, new_backend_generation: Generation) {
        self.pending = None;
        self.submitted = None;
        self.metrics.device_resets += 1;

        if let Some(mut visible) = self.visible {
            visible.backend = new_backend_generation;
            self.visible = None;
        }
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
        self.metrics.max_pending_or_in_flight =
            self.metrics.max_pending_or_in_flight.max(self.depth() as u64);
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

        s.device_loss(Generation(2));
        assert_eq!(s.depth(), 0);
        assert_eq!(s.visible(), None);
        assert_eq!(s.metrics().device_resets, 1);
        assert!(!s.complete_and_present(id(1, 1)));
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
