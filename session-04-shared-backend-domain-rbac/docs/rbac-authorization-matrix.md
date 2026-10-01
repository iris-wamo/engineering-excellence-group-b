# RBAC Authorization Matrix

## Overview
This document defines the Role-Based Access Control (RBAC) permissions matrix for TaskFlow, mapping roles to resources and allowed/denied actions.

## Roles
- `admin`: System-level administrator
- `manager`: Project/Workspace manager
- `member`: Individual contributor / workspace member

---

## Authorization Matrix

| Role | Resource | Action | Allowed? | Notes / Conditions |
|------|----------|--------|----------|-------------------|
| admin | Users | create, read, update, delete | Yes | Full user management |
| admin | Projects | create, read, update, delete | Yes | Global access |
| admin | Tasks | create, read, update, delete | Yes | Global access |
| manager | Users | read | Yes | Within workspace/project |
| manager | Projects | read, update | Yes | Owned / assigned projects |
| manager | Tasks | create, read, update, assign | Yes | Within managed project |
| member | Users | read | Yes | Basic directory listing |
| member | Projects | read | Yes | Assigned projects |
| member | Tasks | read | Yes | Assigned projects |
| member | Tasks | update_status | Conditional | Only tasks assigned to the member |
| member | Tasks | create, delete | No | Negative test case |
| unauthenticated | Any | any protected endpoint | No | Returns 401 Unauthorized |
