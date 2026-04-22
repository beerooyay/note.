use std::ffi::OsString;
use std::path::{Path, PathBuf};

#[derive(serde::Deserialize)]
pub struct FileTask {
    pub path: String,
    pub r#type: String,
}

#[derive(serde::Deserialize)]
pub struct ConvertTask {
    pub path: String,
    pub r#type: String,
    pub target: String,
}

#[derive(serde::Serialize)]
pub struct FileCard {
    pub id: String,
    pub name: String,
    pub path: String,
    pub size: u64,
    pub r#type: String,
}

fn kind(path: &Path, metadata: &std::fs::Metadata) -> String {
    let extension = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    match extension.as_str() {
        "pdf" => "pdf",
        "jpg" | "jpeg" | "png" | "gif" | "webp" | "heic" => "image",
        "doc" | "docx" | "ppt" | "pptx" | "xls" | "xlsx" | "odt" | "rtf" => "office",
        "mp3" | "wav" | "m4a" | "flac" | "aac" => "audio",
        "mp4" | "mov" | "avi" | "mkv" | "webm" => "video",
        "txt" | "md" | "json" | "yaml" | "yml" | "toml" => "text",
        _ if metadata.is_dir() => "folder",
        _ => "unknown",
    }
    .to_string()
}

fn card(path: PathBuf) -> Result<FileCard, String> {
    let metadata = std::fs::metadata(&path).map_err(|e| e.to_string())?;
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();
    Ok(FileCard {
        id: uuid::Uuid::new_v4().to_string(),
        name,
        path: path.to_string_lossy().into_owned(),
        size: metadata.len(),
        r#type: kind(&path, &metadata),
    })
}

fn stem(path: &Path) -> String {
    path.file_stem().and_then(|s| s.to_str()).unwrap_or("file").to_string()
}

fn ext(path: &Path) -> String {
    path.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase()
}

fn sibling(path: &Path, suffix: &str, extension: &str) -> PathBuf {
    let mut name = OsString::from(stem(path));
    name.push(suffix);
    if !extension.is_empty() {
        name.push(".");
        name.push(extension);
    }
    path.with_file_name(name)
}

fn run(cmd: &str, args: &[&str], hint: &str) -> Result<(), String> {
    let output = std::process::Command::new(cmd)
        .args(args)
        .output()
        .map_err(|e| format!("{}: {}", hint, e))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn compress_one(task: &FileTask) -> Result<PathBuf, String> {
    let path = PathBuf::from(&task.path);
    let in_str = path.to_string_lossy().into_owned();
    match task.r#type.as_str() {
        "pdf" => {
            let out = sibling(&path, "-min", "pdf");
            let out_str = out.to_string_lossy().into_owned();
            run("qpdf", &["--linearize", &in_str, &out_str], "qpdf not found — brew install qpdf")?;
            Ok(out)
        }
        "image" => {
            let out_ext = match ext(&path).as_str() {
                "png" => "png",
                "webp" => "webp",
                _ => "jpg",
            };
            let out = sibling(&path, "-min", out_ext);
            let out_str = out.to_string_lossy().into_owned();
            let quality = if out_ext == "png" { "82" } else { "78" };
            run("magick", &[&in_str, "-strip", "-quality", quality, &out_str], "magick not found — brew install imagemagick")?;
            Ok(out)
        }
        "audio" => {
            let out = sibling(&path, "-min", "m4a");
            let out_str = out.to_string_lossy().into_owned();
            run("ffmpeg", &["-y", "-i", &in_str, "-vn", "-c:a", "aac", "-b:a", "96k", &out_str], "ffmpeg not found — brew install ffmpeg")?;
            Ok(out)
        }
        "video" => {
            let out = sibling(&path, "-min", "mp4");
            let out_str = out.to_string_lossy().into_owned();
            run("ffmpeg", &["-y", "-i", &in_str, "-vcodec", "libx264", "-crf", "30", "-preset", "veryfast", "-acodec", "aac", "-b:a", "96k", &out_str], "ffmpeg not found — brew install ffmpeg")?;
            Ok(out)
        }
        _ => Err(format!("compress is not supported for {}", task.r#type)),
    }
}

#[tauri::command]
pub async fn ingest_files(paths: Vec<String>) -> Result<Vec<FileCard>, String> {
    let mut cards = Vec::new();
    for path in paths {
        cards.push(card(PathBuf::from(path))?);
    }
    Ok(cards)
}

#[tauri::command]
pub async fn run_compress(files: Vec<FileTask>) -> Result<Vec<FileCard>, String> {
    let mut out = Vec::new();
    for file in files {
        out.push(card(compress_one(&file)?)?);
    }
    Ok(out)
}

const IMAGE_EXTS: &[&str] = &["png", "jpg", "jpeg", "webp", "heic", "gif", "bmp", "tiff", "tif"];
const TEXT_EXTS: &[&str] = &["txt", "md", "pdf", "docx", "html", "htm", "rtf", "epub", "tex"];
const AUDIO_EXTS: &[&str] = &["mp3", "m4a", "wav", "flac", "aac", "ogg"];
const VIDEO_EXTS: &[&str] = &["mp4", "mov", "mkv", "webm", "gif"];

fn convert_one(task: &ConvertTask) -> Result<PathBuf, String> {
    let path = PathBuf::from(&task.path);
    let in_str = path.to_string_lossy().into_owned();
    let target = task.r#target.to_lowercase();
    let out = sibling(&path, "-converted", &target);
    let out_str = out.to_string_lossy().into_owned();

    let src_ext = ext(&path);
    let is_src_image = IMAGE_EXTS.contains(&src_ext.as_str());
    let is_dst_image = IMAGE_EXTS.contains(&target.as_str());
    let is_src_text = src_ext == "pdf" || TEXT_EXTS.contains(&src_ext.as_str()) || matches!(task.r#type.as_str(), "text" | "pdf" | "office");
    let is_dst_text = TEXT_EXTS.contains(&target.as_str());
    let is_src_audio = AUDIO_EXTS.contains(&src_ext.as_str());
    let is_dst_audio = AUDIO_EXTS.contains(&target.as_str());
    let is_src_video = VIDEO_EXTS.contains(&src_ext.as_str());
    let is_dst_video = VIDEO_EXTS.contains(&target.as_str());

    if is_src_image && is_dst_image {
        let fmt = match target.as_str() {
            "jpg" | "jpeg" => "jpeg",
            "tif" => "tiff",
            other => other,
        };
        run("sips", &["-s", "format", fmt, &in_str, "--out", &out_str], "sips missing")?;
        return Ok(out);
    }
    if is_src_text && is_dst_text {
        run("pandoc", &[&in_str, "-o", &out_str], "pandoc not found — brew install pandoc")?;
        return Ok(out);
    }
    if (is_src_audio || is_src_video) && (is_dst_audio || is_dst_video) {
        run("ffmpeg", &["-y", "-i", &in_str, &out_str], "ffmpeg not found — brew install ffmpeg")?;
        return Ok(out);
    }
    Err(format!("cannot convert {} to {}", src_ext, target))
}

#[tauri::command]
pub async fn run_convert(files: Vec<ConvertTask>) -> Result<Vec<FileCard>, String> {
    let mut out = Vec::new();
    for file in files {
        out.push(card(convert_one(&file)?)?);
    }
    Ok(out)
}

#[tauri::command]
pub fn convert_targets(kind: String) -> Vec<String> {
    match kind.as_str() {
        "image" => IMAGE_EXTS.iter().map(|s| s.to_string()).collect(),
        "pdf" => vec!["txt".into(), "md".into(), "html".into(), "docx".into()],
        "text" => TEXT_EXTS.iter().filter(|x| **x != "pdf").map(|s| s.to_string()).collect(),
        "office" => vec!["pdf".into(), "txt".into(), "md".into(), "html".into(), "docx".into()],
        "audio" => AUDIO_EXTS.iter().map(|s| s.to_string()).collect(),
        "video" => VIDEO_EXTS.iter().map(|s| s.to_string()).collect(),
        _ => vec![],
    }
}
