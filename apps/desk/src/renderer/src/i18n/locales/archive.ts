// All projects › Archive: archive wrong / superseded projects, find them under 「已归档」, restore them. Nothing on
// disk is deleted.

export const archiveEn = {
  'projects.archive': 'Archive',
  'projects.restore': 'Restore',
  'projects.f.archived': 'Archived {n}',
  'projects.archivedN': '{n, plural, one {Archived # project} other {Archived # projects}}',
  'projects.archiveHint': 'Nothing was deleted — find it under Archived.',
  'projects.restoredN': '{n, plural, one {Restored # project} other {Restored # projects}}',
  'projects.archivedOn': 'Archived {date}',
  'projects.archivedNoDate': 'Archived',
  'projects.archiveRunning': '“{name}” is still running. Wait until it finishes (or stop it), then archive it.',
  'projects.archivedEmpty': 'Nothing archived',
  'projects.archivedEmptyHint': 'Archive a project from its menu to tidy the list. Nothing is deleted, and you can restore it any time.',
  'project.archivedBanner': 'This project is archived: it’s hidden from All projects. Nothing was deleted.',
  // an empty filter without search text says what is missing (with search text: projects.noMatch)
  'projects.none.all': 'No projects match these filters',
  'projects.none.running': 'No running projects',
  'projects.none.you': 'Nothing needs you right now',
  'projects.none.done': 'No ready projects yet',
  'projects.none.failed': 'No stopped projects',
  'projects.none.archived': 'No archived projects match these filters',
  'projects.none.type': 'No “{type}” projects',
};

type ArchiveKey = keyof typeof archiveEn;

export const archiveZh: Record<ArchiveKey, string> = {
  'projects.archive': '归档',
  'projects.restore': '恢复',
  'projects.f.archived': '已归档 {n}',
  'projects.archivedN': '已归档 {n} 个项目',
  'projects.archiveHint': '什么都没删，可在「已归档」里找回。',
  'projects.restoredN': '已恢复 {n} 个项目',
  'projects.archivedOn': '{date} 归档',
  'projects.archivedNoDate': '已归档',
  'projects.archiveRunning': '「{name}」还在运行，等它跑完（或先停止）再归档。',
  'projects.archivedEmpty': '没有已归档的项目',
  'projects.archivedEmptyHint': '在项目的菜单里点「归档」就能收起它，文件不会删除，随时可以恢复。',
  'project.archivedBanner': '这个项目已归档，不在「全部项目」里显示。文件都还在。',
  'projects.none.all': '没有符合筛选条件的项目',
  'projects.none.running': '没有进行中的项目',
  'projects.none.you': '目前没有需要你处理的项目',
  'projects.none.done': '还没有做好的项目',
  'projects.none.failed': '没有停下的项目',
  'projects.none.archived': '没有符合筛选条件的已归档项目',
  'projects.none.type': '没有「{type}」类型的项目',
};

export const archiveFr: Record<ArchiveKey, string> = {
  'projects.archive': 'Archiver',
  'projects.restore': 'Restaurer',
  'projects.f.archived': 'Archivés ({n})',
  'projects.archivedN': '{n, plural, one {# projet archivé} other {# projets archivés}}',
  'projects.archiveHint': 'Rien n’a été supprimé — retrouvez-le dans Archivés.',
  'projects.restoredN': '{n, plural, one {# projet restauré} other {# projets restaurés}}',
  'projects.archivedOn': 'Archivé le {date}',
  'projects.archivedNoDate': 'Archivé',
  'projects.archiveRunning': '« {name} » est encore en cours. Attendez la fin (ou arrêtez-le), puis archivez-le.',
  'projects.archivedEmpty': 'Aucun projet archivé',
  'projects.archivedEmptyHint': 'Archivez un projet depuis son menu pour alléger la liste. Rien n’est supprimé, vous pouvez le restaurer à tout moment.',
  'project.archivedBanner': 'Ce projet est archivé : il n’apparaît plus dans Tous les projets. Rien n’a été supprimé.',
  'projects.none.all': 'Aucun projet ne correspond à ces filtres',
  'projects.none.running': 'Aucun projet en cours',
  'projects.none.you': 'Rien ne vous attend pour le moment',
  'projects.none.done': 'Aucun projet prêt pour l’instant',
  'projects.none.failed': 'Aucun projet arrêté',
  'projects.none.archived': 'Aucun projet archivé ne correspond à ces filtres',
  'projects.none.type': 'Aucun projet de type « {type} »',
};
