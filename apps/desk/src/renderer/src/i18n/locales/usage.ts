// Opt-in anonymous usage counts: the first-run choice, Settings › General › Privacy, the one-time ask for profiles
// made before the choice existed. One sentence says exactly what is sent; the docs page lists every field.

export const usageEn = {
  'usage.title': 'Privacy',
  'usage.toggle': 'Share anonymous usage counts',
  'usage.what':
    'Off unless you turn it on. Sends only a random ID, the app version, your OS, the app language and counts such as “a batch of 12 clips finished”; never file names, text, prompts or footage.',
  'usage.link': 'What is sent',
  'usage.devOff': 'This development build never sends anything.',
  'usage.id': 'Anonymous ID',
  'usage.idHint': 'Made on this computer at random. A new ID starts counting from zero.',
  'usage.reset': 'New ID',
  'usage.delete': 'Delete my usage data',
  'usage.deleteHint': 'Removes everything this ID sent from our server, then gives you a new ID.',
  'usage.deleted': 'Deleted from the server ({n, plural, one {# record} other {# records}}). You have a new ID.',
  'usage.deleteFailed': 'Could not reach the server ({error}). Nothing was deleted; try again when you are online.',
  'usage.lastSent': 'Last sent {day}',
  'usage.ask.title': 'Help count Reelfold users?',
  'usage.ask.yes': 'Share counts',
  'usage.ask.no': 'No thanks',
};

type UsageKey = keyof typeof usageEn;

export const usageZh: Record<UsageKey, string> = {
  'usage.title': '隐私',
  'usage.toggle': '分享匿名使用次数',
  'usage.what': '默认关闭，你打开才会发送。只发送随机 ID、版本号、系统、界面语言和次数（比如“一批 12 条切片完成”）；绝不发送文件名、文字、指令或素材。',
  'usage.link': '具体发送什么',
  'usage.devOff': '这是开发版，不会发送任何内容。',
  'usage.id': '匿名 ID',
  'usage.idHint': '在这台电脑上随机生成。换新 ID 后从零开始计数。',
  'usage.reset': '换新 ID',
  'usage.delete': '删除我的使用数据',
  'usage.deleteHint': '从我们的服务器删除这个 ID 发送过的所有记录，然后换一个新 ID。',
  'usage.deleted': '已从服务器删除（{n} 条记录）。已换新 ID。',
  'usage.deleteFailed': '连不上服务器（{error}），没有删除任何内容；联网后再试一次。',
  'usage.lastSent': '上次发送：{day}',
  'usage.ask.title': '帮我们统计千剪的用户数？',
  'usage.ask.yes': '分享次数',
  'usage.ask.no': '不用了',
};

export const usageFr: Record<UsageKey, string> = {
  'usage.title': 'Confidentialité',
  'usage.toggle': 'Partager des statistiques d’usage anonymes',
  'usage.what':
    'Désactivé tant que vous ne l’activez pas. N’envoie qu’un identifiant aléatoire, la version de l’app, votre système, la langue de l’app et des compteurs comme « un lot de 12 clips terminé » ; jamais de noms de fichiers, de texte, de consignes ni de vidéo.',
  'usage.link': 'Ce qui est envoyé',
  'usage.devOff': 'Cette version de développement n’envoie jamais rien.',
  'usage.id': 'Identifiant anonyme',
  'usage.idHint': 'Créé au hasard sur cet ordinateur. Un nouvel identifiant repart de zéro.',
  'usage.reset': 'Nouvel identifiant',
  'usage.delete': 'Supprimer mes données d’usage',
  'usage.deleteHint': 'Efface de notre serveur tout ce que cet identifiant a envoyé, puis vous en donne un nouveau.',
  'usage.deleted': 'Supprimé du serveur ({n, plural, one {# enregistrement} other {# enregistrements}}). Vous avez un nouvel identifiant.',
  'usage.deleteFailed': 'Serveur injoignable ({error}). Rien n’a été supprimé ; réessayez une fois en ligne.',
  'usage.lastSent': 'Dernier envoi le {day}',
  'usage.ask.title': 'Nous aider à compter les utilisateurs de Reelfold ?',
  'usage.ask.yes': 'Partager',
  'usage.ask.no': 'Non merci',
};
