from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import update, func
from sqlalchemy.orm import Session
from .db import get_db
from .auth import current_user, manager
from .models.core import User, Task, TaskEvent
from .models.work import Project, Sprint, IssueDetail, Comment, WorkLog, Watcher, IssueLink, Attachment, ProjectMember
from .services.projects import validate_owner, validate_assignee, validate_capacity
from .api import public, scoped, save, audit, notify, team_user
from . import work_schemas as s

router = APIRouter(prefix="/api/v1", tags=["work management"])


def issue_access(db, task_id, user):
    task = scoped(db, Task, task_id, user)
    # Project issues are collaborative within a team; legacy standalone tasks
    # retain their original assignee-only visibility for members.
    if user.role != "lead" and task.assignee_id != user.id and not db.get(IssueDetail, task_id):
        raise HTTPException(404, "Issue not found")
    return task


def issue_json(db, task):
    detail = db.get(IssueDetail, task.id)
    return {**public(task), **(public(detail) if detail else {})}


@router.get("/projects")
def projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    return [public(row) for row in db.query(Project).filter_by(team_id=user.team_id).order_by(Project.id).limit(200)]


@router.post("/projects", status_code=201)
def create_project(data: s.ProjectInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    if db.query(Project).filter_by(team_id=user.team_id, key=data.key).first():
        raise HTTPException(409, "Project key already exists")
    validate_owner(db, data.owner_id, user.team_id)
    row = Project(team_id=user.team_id, **data.model_dump())
    db.add(row); db.flush(); audit(db, user, "project_created", row); save(db)
    return public(row)


@router.get("/projects/{project_id}")
def project_details(project_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=scoped(db,Project,project_id,user)
    members=db.query(ProjectMember).filter_by(team_id=user.team_id,project_id=project_id).order_by(ProjectMember.id).all()
    return {**public(row),"members":[{**public(m),"name":db.get(User,m.user_id).name} for m in members]}


@router.patch("/projects/{project_id}")
def edit_project(project_id:int,data:s.ProjectEdit,db:Session=Depends(get_db),user:User=Depends(manager)):
    row=scoped(db,Project,project_id,user)
    db.query(Project).filter_by(id=project_id).with_for_update().first()
    db.refresh(row)
    changes=data.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("name","description")):
        raise HTTPException(422,"Name and description cannot be null")
    planned=changes.get("planned_date",row.planned_date)
    release=changes.get("release_date",row.release_date)
    if planned and release and release<planned:
        raise HTTPException(422,"Release date must be on or after planned date")
    validate_owner(db,changes.get("owner_id",row.owner_id),user.team_id)
    for key,value in changes.items():
        setattr(row,key,value)
    audit(db,user,"project_updated",row);save(db)
    return public(row)


@router.get("/projects/{project_id}/members")
def project_members(project_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    scoped(db,Project,project_id,user)
    return [{**public(row),"name":db.get(User,row.user_id).name} for row in db.query(ProjectMember).filter_by(team_id=user.team_id,project_id=project_id).order_by(ProjectMember.id)]


@router.post("/projects/{project_id}/members")
def allocate_member(project_id:int,data:s.MemberInput,db:Session=Depends(get_db),user:User=Depends(manager)):
    project=scoped(db,Project,project_id,user)
    db.query(Project).filter_by(id=project.id).with_for_update().first()
    employee=scoped(db,User,data.user_id,user)
    db.query(User).filter_by(id=employee.id).with_for_update().first()
    if employee.role!="member" or (data.active and not employee.active):
        raise HTTPException(422,"Allocate active team members only")
    row=db.query(ProjectMember).filter_by(project_id=project_id,user_id=data.user_id).first()
    if row and not data.active:
        unfinished=db.query(Task).join(IssueDetail,IssueDetail.task_id==Task.id).filter(
            IssueDetail.project_id==project_id,Task.assignee_id==employee.id,Task.status!="done").first()
        if unfinished:
            raise HTTPException(409,"Reassign or finish this employee's open project issues before removing them")
    validate_capacity(db,user.team_id,data,row.id if row else None)
    if not row:
        row=ProjectMember(team_id=user.team_id,project_id=project_id,user_id=data.user_id)
        db.add(row)
    for key,value in data.model_dump().items():
        setattr(row,key,value)
    db.flush();audit(db,user,"project_member_allocated" if data.active else "project_member_removed",row);save(db)
    return {**public(row),"name":employee.name}


@router.get("/sprints")
def sprints(project_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    query = db.query(Sprint).filter_by(team_id=user.team_id)
    if project_id is not None:
        scoped(db, Project, project_id, user)
        query = query.filter_by(project_id=project_id)
    return [public(row) for row in query.order_by(Sprint.id.desc()).limit(200)]


@router.post("/sprints", status_code=201)
def create_sprint(data: s.SprintInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    scoped(db, Project, data.project_id, user)
    row = Sprint(team_id=user.team_id, **data.model_dump())
    db.add(row); db.flush(); audit(db, user, "sprint_created", row); save(db)
    return public(row)


@router.post("/sprints/{sprint_id}/status")
def sprint_status(sprint_id: int, data: s.SprintTransition, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = scoped(db, Sprint, sprint_id, user)
    # Lock the project so competing starts cannot create two active sprints.
    db.query(Project).filter_by(id=row.project_id).with_for_update().first()
    db.refresh(row)
    if data.status == "active":
        if row.status != "planned" or db.query(Sprint).filter_by(project_id=row.project_id, status="active").first():
            raise HTTPException(409, "Only a planned sprint can start; project already may have an active sprint")
    elif row.status != "active":
        raise HTTPException(409, "Only an active sprint can complete")
    else:
        issues = db.query(IssueDetail, Task).join(Task, Task.id == IssueDetail.task_id).filter(IssueDetail.sprint_id == row.id).all()
        row.snapshot = [{"task_id":task.id,"key":detail.issue_key,"status":task.status,"story_points":detail.story_points} for detail, task in issues]
        row.completed_at = datetime.utcnow()
        for detail, task in issues:
            if task.status != "done":
                detail.sprint_id = None
    row.status = data.status
    audit(db, user, "sprint_" + data.status, row); save(db)
    return public(row)


def validate_sprint(db, sprint_id, project_id, user):
    if sprint_id is not None:
        sprint = scoped(db, Sprint, sprint_id, user)
        if sprint.project_id != project_id or sprint.status == "completed":
            raise HTTPException(422, "Sprint must be open and belong to the issue project")


@router.get("/issues")
def issues(project_id: int | None = None, sprint_id: int | None = None, backlog: bool = False,
           q: str = Query(default="", max_length=200), offset: int = Query(default=0, ge=0),
           db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    query = db.query(Task).join(IssueDetail, IssueDetail.task_id == Task.id).filter(Task.team_id == user.team_id)
    if project_id is not None:
        scoped(db, Project, project_id, user)
        query = query.filter(IssueDetail.project_id == project_id)
    if sprint_id is not None:
        scoped(db, Sprint, sprint_id, user)
        query = query.filter(IssueDetail.sprint_id == sprint_id)
    if backlog:
        query = query.filter(IssueDetail.sprint_id.is_(None), Task.status != "done")
    if q:
        query = query.filter(Task.title.ilike(f"%{q}%") | IssueDetail.issue_key.ilike(f"%{q}%"))
    return [issue_json(db, task) for task in query.order_by(Task.id.desc()).offset(offset).limit(200)]


@router.post("/issues", status_code=201)
def create_issue(data: s.IssueInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    project = scoped(db, Project, data.project_id, user)
    db.query(Project).filter_by(id=project.id).with_for_update().first()
    if project.status != "active":
        raise HTTPException(409, "Project archived")
    assignee = scoped(db, User, data.assignee_id, user)
    validate_assignee(db,assignee,project.id,data.planned_date)
    validate_sprint(db, data.sprint_id, project.id, user)
    if data.kind == "subtask" and data.parent_id is None:
        raise HTTPException(422, "Subtask requires a parent")
    if data.parent_id is not None:
        parent = db.get(IssueDetail, data.parent_id)
        if not parent or parent.project_id != project.id or parent.team_id != user.team_id or parent.kind == "subtask":
            raise HTTPException(422, "Parent must be a non-subtask in this project")
    # Atomic UPDATE RETURNING works in PostgreSQL and modern SQLite.
    number = db.execute(update(Project).where(Project.id == project.id).values(next_number=Project.next_number+1).returning(Project.next_number)).scalar_one() - 1
    task = Task(team_id=user.team_id, created_by=user.id, **data.model_dump(include={"title","description","assignee_id","estimate_minutes","due_date"}))
    db.add(task); db.flush()
    detail = IssueDetail(task_id=task.id, team_id=user.team_id, number=number, issue_key=f"{project.key}-{number}",
                        **data.model_dump(include={"project_id","sprint_id","parent_id","kind","priority","story_points","labels","cost","currency","planned_date","release_date"}))
    db.add(detail)
    db.add(TaskEvent(team_id=user.team_id,task_id=task.id,actor_id=user.id,to_status="assigned"))
    notify(db,assignee,"task_assigned",task.id); audit(db,user,"issue_created",task); save(db)
    return issue_json(db,task)


@router.get("/issues/{task_id}")
def issue(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = issue_access(db, task_id, user)
    return {**issue_json(db,task),
            "events":[public(row) for row in db.query(TaskEvent).filter_by(team_id=user.team_id,task_id=task_id).order_by(TaskEvent.id)],
            "comments":[public(row) for row in db.query(Comment).filter_by(team_id=user.team_id,task_id=task_id).order_by(Comment.id)],
            "work_logs":[public(row) for row in db.query(WorkLog).filter_by(team_id=user.team_id,task_id=task_id).order_by(WorkLog.id)],
            "watchers":[row.user_id for row in db.query(Watcher).filter_by(team_id=user.team_id,task_id=task_id)],
            "links":[public(row) for row in db.query(IssueLink).filter(IssueLink.team_id==user.team_id,(IssueLink.source_id==task_id)|(IssueLink.target_id==task_id))],
            "attachments":[public(row,("id","filename","size","author_id","created_at")) for row in db.query(Attachment).filter_by(team_id=user.team_id,task_id=task_id)]}


@router.patch("/issues/{task_id}")
def edit_issue(task_id: int, data: s.IssueEdit, db: Session = Depends(get_db), user: User = Depends(manager)):
    task = scoped(db,Task,task_id,user)
    detail = db.get(IssueDetail,task_id)
    if not detail:
        raise HTTPException(404,"Project issue not found")
    db.query(Project).filter_by(id=detail.project_id).with_for_update().first()
    assignee = scoped(db,User,data.assignee_id,user)
    validate_assignee(db,assignee,detail.project_id,data.planned_date if "planned_date" in data.model_fields_set else detail.planned_date)
    planned=data.planned_date if "planned_date" in data.model_fields_set else detail.planned_date
    release=data.release_date if "release_date" in data.model_fields_set else detail.release_date
    if planned and release and release<planned:
        raise HTTPException(422,"Release date must be on or after planned date")
    if data.kind=="subtask" and detail.parent_id is None:
        raise HTTPException(422,"Subtask requires a parent")
    if data.kind=="subtask" and db.query(IssueDetail).filter_by(parent_id=task_id).first():
        raise HTTPException(422,"An issue with children cannot become a subtask")
    validate_sprint(db,data.sprint_id,detail.project_id,user)
    previous = task.assignee_id
    for name in ("title","description","assignee_id","due_date"):
        setattr(task,name,getattr(data,name))
    for name in ("sprint_id","priority","story_points","labels"):
        setattr(detail,name,getattr(data,name))
    for name in ("cost","currency","planned_date","release_date","kind"):
        if name in data.model_fields_set:
            if name=="kind" and data.kind is None:
                raise HTTPException(422,"Issue type cannot be null")
            setattr(detail,name,getattr(data,name))
    if "estimate_minutes" in data.model_fields_set:
        if data.estimate_minutes is None:
            raise HTTPException(422,"Estimate cannot be null")
        task.estimate_minutes=data.estimate_minutes
    if previous != task.assignee_id:
        notify(db,assignee,"task_assigned",task.id)
    audit(db,user,"issue_updated",task); save(db)
    return issue_json(db,task)


@router.post("/issues/{task_id}/comments",status_code=201)
def comment(task_id:int, data:s.CommentInput, db:Session=Depends(get_db), user:User=Depends(current_user)):
    issue_access(db,task_id,user)
    row=Comment(team_id=user.team_id,task_id=task_id,author_id=user.id,body=data.body)
    db.add(row); db.flush(); audit(db,user,"comment_created",row)
    for watcher in db.query(Watcher).filter_by(task_id=task_id,team_id=user.team_id):
        if watcher.user_id!=user.id:
            notify(db,db.get(User,watcher.user_id),"issue_comment",task_id)
    save(db)
    return public(row)


@router.post("/issues/{task_id}/watch")
def watch(task_id:int,data:s.WatchInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    issue_access(db,task_id,user)
    existing=db.get(Watcher,(task_id,user.id))
    if data.watching and not existing:
        db.add(Watcher(task_id=task_id,user_id=user.id,team_id=user.team_id))
    elif not data.watching and existing:
        db.delete(existing)
    save(db)
    return {"watching":data.watching}


@router.post("/issues/{task_id}/links",status_code=201)
def link(task_id:int,data:s.LinkInput,db:Session=Depends(get_db),user:User=Depends(manager)):
    source=issue_access(db,task_id,user); target=issue_access(db,data.target_id,user)
    first=db.get(IssueDetail,source.id); second=db.get(IssueDetail,target.id)
    if not first or not second or first.project_id!=second.project_id or source.id==target.id:
        raise HTTPException(422,"Link two different issues within one project")
    db.query(Project).filter_by(id=first.project_id).with_for_update().first()
    if db.query(IssueLink).filter_by(source_id=task_id,target_id=data.target_id,kind=data.kind).first():
        raise HTTPException(409,"Link already exists")
    if data.kind=="blocks":
        edges=db.query(IssueLink).filter_by(team_id=user.team_id,kind="blocks").all()
        stack=[target.id]; seen=set()
        while stack:
            node=stack.pop()
            if node==source.id:
                raise HTTPException(422,"Dependency would create a cycle")
            if node in seen:
                continue
            seen.add(node); stack.extend(edge.target_id for edge in edges if edge.source_id==node)
    row=IssueLink(team_id=user.team_id,source_id=source.id,target_id=target.id,kind=data.kind)
    db.add(row); db.flush(); audit(db,user,"issue_link_created",row); save(db)
    return public(row)


@router.post("/issues/{task_id}/attachments",status_code=201)
def upload(task_id:int,file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    issue_access(db,task_id,user)
    content=file.file.read(5*1024*1024+1)
    if not content or len(content)>5*1024*1024:
        raise HTTPException(422,"Attachment must contain 1 byte to 5 MB")
    name=(file.filename or "attachment").replace("\\","/").split("/")[-1][:200]
    name="".join(c for c in name if c.isprintable()) or "attachment"
    row=Attachment(team_id=user.team_id,task_id=task_id,author_id=user.id,filename=name,size=len(content),content=content)
    db.add(row); db.flush(); audit(db,user,"attachment_created",row); save(db)
    return public(row,("id","filename","size","created_at"))


@router.get("/attachments/{attachment_id}/download")
def download(attachment_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=scoped(db,Attachment,attachment_id,user)
    issue_access(db,row.task_id,user)
    from urllib.parse import quote
    return Response(content=row.content,media_type="application/octet-stream",
                    headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(row.filename,safe=""),"X-Content-Type-Options":"nosniff","Cache-Control":"no-store"})


@router.post("/issues/{task_id}/work-logs",status_code=201)
def work_log(task_id:int,data:s.WorkLogInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    issue_access(db,task_id,user)
    db.query(User).filter_by(id=user.id).with_for_update().first()
    total=db.query(func.coalesce(func.sum(WorkLog.minutes),0)).filter_by(user_id=user.id,work_date=data.work_date).scalar()
    if total + data.minutes > 1440:
        raise HTTPException(422,"Daily logged work cannot exceed 24 hours")
    row=WorkLog(team_id=user.team_id,task_id=task_id,user_id=user.id,**data.model_dump())
    db.add(row); db.flush(); audit(db,user,"work_logged",row); save(db)
    return public(row)
