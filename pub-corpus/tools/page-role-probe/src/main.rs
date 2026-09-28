use pub_reader::analyze_mature_0x2c_page_roles;
use std::{env, fs, io::Cursor};

fn main() {
    let mut args = env::args().skip(1);
    let path = args.next().expect("usage: lalamu-page-role-probe <file.pub>");
    if args.next().is_some() {
        eprintln!("unexpected extra arguments");
        std::process::exit(2);
    }

    let bytes = match fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) => {
            eprintln!("read {path}: {error}");
            std::process::exit(2);
        }
    };

    match analyze_mature_0x2c_page_roles(Cursor::new(bytes)) {
        Ok(receipt) => {
            serde_json::to_writer(std::io::stdout(), &receipt).expect("serialize page-role receipt");
            println!();
        }
        Err(error) => {
            eprintln!("{error:#}");
            std::process::exit(1);
        }
    }
}
