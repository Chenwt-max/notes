"""课程与章节目录；独立于提取任务，整理目录不改动源文件或任务。"""
from __future__ import annotations

import time
import uuid
import json
from pathlib import Path

from .store import connect


def database():
    db = connect()
    db.execute('CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY, course_id TEXT NOT NULL, path TEXT COLLATE NOCASE UNIQUE NOT NULL, title TEXT NOT NULL, position INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS catalog_state(key TEXT PRIMARY KEY, value TEXT)')
    db.commit()
    return db


def title(value):
    value = str(value or '').strip()
    if not value or len(value)>120:
        raise ValueError('名称请填写1至120个字')
    return value


def require_course(db, course_id):
    if not db.execute('SELECT id FROM courses WHERE id=?',(course_id,)).fetchone():
        raise ValueError('课程不存在')


def initialize(paths):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT key FROM catalog_state WHERE key="initialized"').fetchone():
            return
        if paths and not db.execute('SELECT id FROM courses LIMIT 1').fetchone():
            course_id = uuid.uuid4().hex[:12]
            db.execute('INSERT INTO courses VALUES(?,?,?)',(course_id,'我的第一门课程',time.time()))
            for index,path in enumerate(paths):
                db.execute('INSERT INTO lessons VALUES(?,?,?,?,?)',
                    (uuid.uuid4().hex[:12],course_id,str(Path(path).resolve()),f'第 {index+1} 节',index))
        db.execute('INSERT INTO catalog_state VALUES("initialized","1")')


def list_courses():
    with database() as db:
        courses = [dict(r) for r in db.execute('SELECT * FROM courses ORDER BY created,id')]
        for course in courses:
            course['lessons'] = [dict(r) for r in db.execute('SELECT * FROM lessons WHERE course_id=? ORDER BY position,id',(course['id'],))]
        return courses


def create_course(value):
    course_id = uuid.uuid4().hex[:12]
    with database() as db:
        db.execute('INSERT INTO courses VALUES(?,?,?)',(course_id,title(value.get('title')),time.time()))
    return {'id':course_id}


def rename_course(course_id,value):
    with database() as db:
        require_course(db,course_id)
        db.execute('UPDATE courses SET title=? WHERE id=?',(title(value.get('title')),course_id))
    return {'ok':True}


def delete_course(course_id):
    """Queue all of this course's runs for cleanup, and remove its catalog entry."""
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        require_course(db,course_id)
        paths={str(Path(r[0]).resolve()).casefold() for r in db.execute('SELECT path FROM lessons WHERE course_id=?',(course_id,))}
        jobs=[r['id'] for r in db.execute('SELECT id,spec FROM jobs')
              if str(Path(json.loads(r['spec'])['path']).resolve()).casefold() in paths]
        for job_id in jobs:
            db.execute('UPDATE jobs SET status="delete_requested",stage="正在删除",updated=?,error="",message="正在停止任务并清理生成资料，原视频保留" WHERE id=?',
                       (time.time(),job_id))
        db.execute('DELETE FROM lessons WHERE course_id=?',(course_id,))
        db.execute('DELETE FROM courses WHERE id=?',(course_id,))
    return {'id':course_id,'job_ids':jobs,'status':'delete_requested' if jobs else 'deleted'}


def add_lessons(course_id,items):
    if not isinstance(items,list) or not items:
        raise ValueError('请选择需要加入的本地视频')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        require_course(db,course_id)
        position = db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM lessons WHERE course_id=?',(course_id,)).fetchone()[0]
        for item in items:
            path = str(Path(item['path']).resolve())
            if db.execute('SELECT id FROM lessons WHERE path=?',(path,)).fetchone():
                raise ValueError('视频已属于一门课程，请在章节整理中移动')
            db.execute('INSERT INTO lessons VALUES(?,?,?,?,?)',
                (uuid.uuid4().hex[:12],course_id,path,title(item.get('title') or Path(path).stem),position))
            position += 1
    return {'ok':True}


def update_lesson(lesson_id,value):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        lesson = db.execute('SELECT * FROM lessons WHERE id=?',(lesson_id,)).fetchone()
        if not lesson:
            raise ValueError('章节不存在')
        course_id = value.get('course_id',lesson['course_id'])
        require_course(db,course_id)
        position = lesson['position']
        if course_id != lesson['course_id']:
            position = db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM lessons WHERE course_id=?',(course_id,)).fetchone()[0]
        db.execute('UPDATE lessons SET course_id=?,title=?,position=? WHERE id=?',
            (course_id,title(value.get('title',lesson['title'])),position,lesson_id))
    return {'ok':True}


def reorder_lessons(course_id,ids):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        require_course(db,course_id)
        existing = {r[0] for r in db.execute('SELECT id FROM lessons WHERE course_id=?',(course_id,))}
        if not isinstance(ids,list) or len(ids)!=len(existing) or set(ids)!=existing:
            raise ValueError('排序必须包含本课程的每一节且不能重复，请刷新后重试')
        for index,lesson_id in enumerate(ids):
            db.execute('UPDATE lessons SET position=? WHERE id=?',(index,lesson_id))
    return {'ok':True}
