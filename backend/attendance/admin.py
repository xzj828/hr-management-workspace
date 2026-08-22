from django.contrib import admin

from .models import (
    AccountProfile,
    AttendancePolicy,
    AttendanceResult,
    CrossDaySuspicion,
    Employee,
    EmployeeTag,
    ImportBatch,
    RawPunchDay,
)


admin.site.register(AccountProfile)
admin.site.register(AttendancePolicy)
admin.site.register(EmployeeTag)
admin.site.register(Employee)
admin.site.register(ImportBatch)
admin.site.register(RawPunchDay)
admin.site.register(AttendanceResult)
admin.site.register(CrossDaySuspicion)
