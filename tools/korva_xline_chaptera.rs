use pub_viewer::{open_mature_0x2c_geometry, BoundedLayoutEnvironment};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{env, fs, process};

#[derive(Serialize)]
struct StoryObservation {
    ordinal: usize,
    text: String,
    utf8_sha256: String,
}

#[derive(Serialize)]
struct ImageObservation {
    ordinal: usize,
    mime: String,
    byte_len: usize,
    sha256: String,
}

#[derive(Serialize)]
struct ChapteraObservation {
    schema_version: &'static str,
    engine: &'static str,
    supported: bool,
    error: Option<String>,
    source_byte_len: usize,
    source_sha256: String,
    stories: Vec<StoryObservation>,
    images: Vec<ImageObservation>,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn sha256(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

fn main() {
    let path = match env::args().nth(1) {
        Some(path) => path,
        None => {
            eprintln!("usage: chaptera_xline_probe <fixture.pub>");
            process::exit(2);
        }
    };
    let bytes = match fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) => {
            eprintln!("read {path}: {error}");
            process::exit(2);
        }
    };

    let source_sha256 = sha256(&bytes);
    let environment = BoundedLayoutEnvironment {
        engine_revision: "korva-xline-chaptera-probe-v1".to_owned(),
        font_set_fingerprint: "not_scored".to_owned(),
        resource_fingerprint: "not_scored".to_owned(),
    };

    let document = match open_mature_0x2c_geometry(&bytes, environment) {
        Ok(document) => document,
        Err(error) => {
            let observation = ChapteraObservation {
                schema_version: "chaptera.korva-xline.chaptera-observation.v1",
                engine: "chaptera",
                supported: false,
                error: Some(format!("{error:#}")),
                source_byte_len: bytes.len(),
                source_sha256,
                stories: Vec::new(),
                images: Vec::new(),
            };
            println!("{}", serde_json::to_string_pretty(&observation).unwrap());
            return;
        }
    };

    let stories = document
        .document
        .stories
        .iter()
        .enumerate()
        .map(|(ordinal, story)| StoryObservation {
            ordinal,
            text: story.text.clone(),
            utf8_sha256: sha256(story.text.as_bytes()),
        })
        .collect::<Vec<_>>();

    let images = document
        .images
        .iter()
        .enumerate()
        .map(|(ordinal, image)| ImageObservation {
            ordinal,
            mime: image.mime.clone(),
            byte_len: image.bytes.len(),
            sha256: sha256(&image.bytes),
        })
        .collect::<Vec<_>>();

    let observation = ChapteraObservation {
        schema_version: "chaptera.korva-xline.chaptera-observation.v1",
        engine: "chaptera",
        supported: true,
        error: None,
        source_byte_len: bytes.len(),
        source_sha256,
        stories,
        images,
    };
    println!("{}", serde_json::to_string_pretty(&observation).unwrap());
}
