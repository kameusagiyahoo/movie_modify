"""Behavioral Node tests for shared browser history and guarded restoration."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for JS unit tests")
def test_history_undo_redo_persistence_and_conflict():
    code = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const items = new Map();
const store = {
  getItem: key => items.get(key) || null,
  setItem: (key,value) => {items.set(key,value)},
  removeItem: key => {items.delete(key)}
};
const window = {localStorage:store};
vm.runInNewContext(fs.readFileSync('docs/edit_history.js','utf8'), {window, Date, JSON, Math});
const History = window.MovieModifyEditHistory.EditHistory;
const s = (yaw=0) => ({segments:[{start:0,end:20,keep:true,mode:'manual',yaw,
 pitch:0,fov:90,keyframes:[]}], selected:0,time:5});
let x = new History({key:'test',identity:{name:'family.mp4',size:900},initial:s()});
assert.strictEqual(x.state().canUndo,false);
assert.strictEqual(x.candidate().status,'empty');
assert.strictEqual(x.checkpoint(s(20),'angle'),true);
assert.strictEqual(x.state().canUndo,true);
assert.strictEqual(x.candidate().status,'available');
assert.strictEqual(x.undo().segments[0].yaw,0);
assert.strictEqual(x.state().canRedo,true);
assert.strictEqual(x.redo().segments[0].yaw,20);
assert.strictEqual(x.undo().segments[0].yaw,0);
assert.strictEqual(x.checkpoint(s(35),'new branch'),true);
assert.strictEqual(x.state().canRedo,false);
assert.strictEqual(x.undo().segments[0].yaw,0);
// Recover from reloading the same movie in the same origin
let fresh = new History({key:'test',identity:{name:'family.mp4',size:900},initial:s()});
let draft=fresh.candidate();
assert.strictEqual(draft.status,'available');
assert.strictEqual(fresh.restore(draft.snapshot,a=>a).segments[0].yaw,35);
// A changed server baseline must NOT be automatically restored.
let newer = new History({key:'test',identity:{name:'family.mp4',size:900},initial:s(80)});
assert.strictEqual(newer.candidate().status,'conflict');
assert.strictEqual(newer.candidate().snapshot.segments[0].yaw,35);
// A different source metadata fingerprint must not receive the draft.
let other = new History({key:'test',identity:{name:'family.mp4',size:901},initial:s()});
assert.strictEqual(other.candidate().status,'invalid');
fresh.markServerSaved(s(35));
assert.strictEqual(fresh.state().canUndo,false);
assert.strictEqual(fresh.candidate().status,'empty');
// Unavailable storage must signal failure, without corrupting edit history.
const broken = {getItem:()=>null,setItem:()=>{throw Error('quota')},removeItem:()=>{}};
const offline = new History({key:'bad',identity:{name:'x'},initial:s(),storage:broken});
offline.checkpoint(s(12),'cut');
assert.strictEqual(offline.state().available,false);
assert.strictEqual(offline.undo().segments[0].yaw,0);
console.log('EditHistory behavioral tests passed');
"""
    run = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                         cwd=ROOT, check=False, timeout=25)
    assert run.returncode == 0, run.stdout + "\n" + run.stderr


def test_pages_and_advanced_use_shared_history():
    pages=(ROOT/"docs/pages.js").read_text(encoding="utf-8")
    studio=(ROOT/"docs/index.html").read_text(encoding="utf-8")
    advanced=(ROOT/"web/index.html").read_text(encoding="utf-8")
    backend=(ROOT/"movie_modify/server.py").read_text(encoding="utf-8")
    for script in [pages,advanced]:
        assert "MovieModifyEditHistory.EditHistory" in script
        assert "undo" in script and "redo" in script
    for label in ["分割", "残す／カット", "画角キー追加", "景色"]:
        assert label in pages
    assert "JSON読込" in pages
    assert "人物追尾" in advanced and "自動カット候補を適用" in advanced
    assert 'id="editUndo"' in studio and 'id="editRedo"' in studio
    assert 'id="editUndo"' in advanced and 'id="editRedo"' in advanced
    assert "/studio/edit_history.js" in backend
    assert "/assets/edit_history.js" in backend
    assert "data.source.name!==file.name" in pages
