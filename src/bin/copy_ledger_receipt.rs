use copy_ledger_proof::{run_source_free_scenario, Scenario};
use serde_json::json;

fn main() {
    let scenarios = [
        Scenario::OpenParse,
        Scenario::MoveNode,
        Scenario::SmallStoryEdit,
        Scenario::GeometryOnlyReflow,
        Scenario::ReplaceImageExport,
    ];
    let receipts = scenarios
        .into_iter()
        .map(run_source_free_scenario)
        .collect::<Vec<_>>();

    let envelope = json!({
        "schema_version": "chaptera.copy-ledger.proof-set.v1",
        "architecture_decision_allowed": false,
        "measurement_semantics": "deterministic_source_free_counters",
        "receipts": receipts,
    });
    println!("{}", serde_json::to_string_pretty(&envelope).expect("serialize receipt set"));
}
