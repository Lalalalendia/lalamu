use frame_scheduler_proof::deterministic_receipt;

fn main() {
    let receipt = deterministic_receipt();
    println!(
        "{}",
        serde_json::to_string_pretty(&receipt).expect("serialize scheduler receipt")
    );
}
