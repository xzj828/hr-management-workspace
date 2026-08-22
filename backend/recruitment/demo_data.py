from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .models import Candidate, JobApplication, RecruitmentJob, Resume


DEMO_PREFIX = "demo:2026-08-22:"

JOBS = {
    "frontend": {
        "title": "Vue 前端工程师",
        "department": "研发中心",
        "headcount": 2,
        "status": RecruitmentJob.Status.OPEN,
        "jd": "负责 Vue 3 人事产品的页面与交互开发。",
    },
    "product": {
        "title": "人事产品经理",
        "department": "产品中心",
        "headcount": 1,
        "status": RecruitmentJob.Status.OPEN,
        "jd": "负责招聘与考勤工作台的产品规划和交付。",
    },
    "implementation": {
        "title": "实施顾问",
        "department": "客户成功部",
        "headcount": 2,
        "status": RecruitmentJob.Status.PAUSED,
        "jd": "负责人事系统上线、培训与客户需求跟进。",
    },
}

CANDIDATES = [
    {"key": "zhou-xiaoning", "name": "周晓宁", "phone": "138****0001", "email": "zhou.xiaoning@example.com", "title": "前端开发工程师", "city": "北京", "job": "frontend", "stage": JobApplication.Stage.NEW},
    {"key": "lin-yuwei", "name": "林雨薇", "phone": "138****0002", "email": "lin.yuwei@example.com", "title": "高级前端工程师", "city": "上海", "job": "frontend", "stage": JobApplication.Stage.TO_SCREEN},
    {"key": "chen-mo", "name": "陈默", "phone": "138****0003", "email": "chen.mo@example.com", "title": "人事产品经理", "city": "杭州", "job": "product", "stage": JobApplication.Stage.COMMUNICATING},
    {"key": "xu-wen", "name": "徐雯", "phone": "138****0004", "email": "xu.wen@example.com", "title": "SaaS 产品经理", "city": "深圳", "job": "product", "stage": JobApplication.Stage.INTERVIEWING},
    {"key": "gao-yuan", "name": "高远", "phone": "138****0005", "email": "gao.yuan@example.com", "title": "HRIS 产品经理", "city": "北京", "job": "product", "stage": JobApplication.Stage.TO_OFFER},
    {"key": "song-yi", "name": "宋怡", "phone": "138****0006", "email": "song.yi@example.com", "title": "实施顾问", "city": "成都", "job": "implementation", "stage": JobApplication.Stage.HIRED},
    {"key": "han-chuan", "name": "韩川", "phone": "138****0007", "email": "han.chuan@example.com", "title": "项目实施工程师", "city": "武汉", "job": "implementation", "stage": JobApplication.Stage.REJECTED},
    {"key": "lu-jia", "name": "陆佳", "phone": "138****0008", "email": "lu.jia@example.com", "title": "Web 前端工程师", "city": "南京", "job": "frontend", "stage": JobApplication.Stage.COMMUNICATING},
    {"key": "tang-ke", "name": "唐可", "phone": "138****0009", "email": "tang.ke@example.com", "title": "客户成功顾问", "city": "重庆", "job": "implementation", "stage": JobApplication.Stage.TO_SCREEN},
    {"key": "he-an", "name": "何安", "phone": "138****0010", "email": "he.an@example.com", "title": "产品专员", "city": "苏州", "job": "product", "stage": JobApplication.Stage.NEW},
]

RESUME_PROFILES = {
    "zhou-xiaoning": {
        "file_name": "zhou-xiaoning.pdf",
        "name": "周晓宁",
        "lines": [
            "应聘岗位：Vue 前端工程师",
            "技能：Vue 3、TypeScript、Vite",
            "经历：虚构科技有限公司，前端工程师，3 年",
            "教育：示例大学，计算机科学，本科",
        ],
    },
    "xu-wen": {
        "file_name": "xu-wen.pdf",
        "name": "徐雯",
        "lines": [
            "应聘岗位：人事产品经理",
            "技能：产品规划、用户研究、数据分析",
            "经历：虚构软件有限公司，产品经理，5 年",
            "教育：示例大学，信息管理，本科",
        ],
    },
    "song-yi": {
        "file_name": "song-yi.pdf",
        "name": "宋怡",
        "lines": [
            "应聘岗位：实施顾问",
            "技能：项目交付、客户培训、需求分析",
            "经历：虚构服务有限公司，实施顾问，4 年",
            "教育：示例大学，人力资源管理，本科",
        ],
    },
}


def build_resume_pdf(profile: dict) -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.setTitle(profile["file_name"])
    page.setFont("STSong-Light", 18)
    page.drawString(54, 790, profile["name"])
    page.setFont("STSong-Light", 10)
    y = 755
    for line in profile["lines"]:
        page.drawString(54, y, line)
        y -= 22
    page.showPage()
    page.save()
    return buffer.getvalue()


def demo_status() -> dict:
    counts = {
        "jobs": RecruitmentJob.objects.filter(is_demo=True).count(),
        "candidates": Candidate.objects.filter(is_demo=True).count(),
        "applications": JobApplication.objects.filter(is_demo=True).count(),
        "resumes": Resume.objects.filter(is_demo=True).count(),
    }
    return {"loaded": any(counts.values()), "counts": counts}


@transaction.atomic
def load_demo_data(actor) -> dict:
    jobs = {}
    candidates = {}
    applications = {}
    created_files = []
    storage = Resume._meta.get_field("file").storage
    try:
        for key, values in JOBS.items():
            job, _ = RecruitmentJob.objects.update_or_create(
                external_id=f"{DEMO_PREFIX}job:{key}",
                is_demo=True,
                defaults={**values, "boss_account": None, "owner": actor},
            )
            jobs[key] = job

        for values in CANDIDATES:
            candidate, _ = Candidate.objects.update_or_create(
                identity_key=f"{DEMO_PREFIX}candidate:{values['key']}",
                defaults={
                    "external_id": "",
                    "name": values["name"],
                    "phone": values["phone"],
                    "email": values["email"],
                    "current_title": values["title"],
                    "current_city": values["city"],
                    "is_demo": True,
                },
            )
            application, _ = JobApplication.objects.update_or_create(
                candidate=candidate,
                job=jobs[values["job"]],
                defaults={
                    "source": "demo",
                    "stage": values["stage"],
                    "owner": actor,
                    "is_demo": True,
                },
            )
            candidates[values["key"]] = candidate
            applications[values["key"]] = application

        for key, profile in RESUME_PROFILES.items():
            if Resume.objects.filter(candidate=candidates[key], is_demo=True).exists():
                continue
            resume = Resume(
                candidate=candidates[key],
                application=applications[key],
                original_name=profile["file_name"],
                content_type="application/pdf",
                source=Resume.Source.DEMO,
                processing_status=Resume.ProcessingStatus.READY,
                is_demo=True,
            )
            content = build_resume_pdf(profile)
            resume.file_size = len(content)
            resume.file.save(profile["file_name"], ContentFile(content), save=False)
            created_files.append(resume.file.name)
            resume.save()
    except Exception:
        for name in created_files:
            storage.delete(name)
        raise

    return demo_status()["counts"]


@transaction.atomic
def clear_demo_data() -> dict:
    resumes = list(Resume.objects.filter(is_demo=True))
    file_names = [resume.file.name for resume in resumes if resume.file]
    storage = Resume._meta.get_field("file").storage
    Resume.objects.filter(is_demo=True).delete()
    JobApplication.objects.filter(is_demo=True).delete()
    Candidate.objects.filter(is_demo=True).delete()
    RecruitmentJob.objects.filter(is_demo=True).delete()
    transaction.on_commit(lambda: [storage.delete(name) for name in file_names])
    return {
        "loaded": False,
        "counts": {"jobs": 0, "candidates": 0, "applications": 0, "resumes": 0},
    }
