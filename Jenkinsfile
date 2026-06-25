pipeline {
  parameters {
    string(name: 'JIRA_ID', description: 'JIRA ticket ID (e.g. DTB-123)', trim: true)
    choice(name: 'COMMIT_FILTER_MODE', choices: ['any','only'], description: 'Commit filter mode: any (default) | only (strict single-ticket)')
    booleanParam(name: 'SKIP_TESTS', defaultValue: false, description: 'Skip test selection (faster, risk report only)')
  }

  agent any

  options {
    timestamps()
    timeout(time: 15, unit: 'MINUTES')
  }

  stages {
    stage('Analyze') {
      steps {
        script {
          if (!params.JIRA_ID?.trim()) error('Provide JIRA_ID parameter')

          def credentialId = scm.userRemoteConfigs[0].credentialsId
          echo "Using Git credential ID: ${credentialId}"

          withCredentials([sshUserPrivateKey(credentialsId: credentialId, keyFileVariable: 'SSH_KEY')]) {
            withEnv([
              "JIRA_ID=${params.JIRA_ID}",
              "COMMIT_FILTER_MODE=${params.COMMIT_FILTER_MODE}",
              "SKIP_TESTS=${params.SKIP_TESTS}"
            ]) {
              sh '''
                export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"
                sed -i "s/^COMMIT_FILTER_MODE=.*/COMMIT_FILTER_MODE=$COMMIT_FILTER_MODE/" ./config.env

                SKIP_FLAG=""
                [[ "$SKIP_TESTS" == "true" ]] && SKIP_FLAG="--skip-tests"

                bash scripts/run_analysis_by_jira_id.sh "$JIRA_ID" \
                  --filter-mode "$COMMIT_FILTER_MODE" $SKIP_FLAG
              '''
            }
          }
        }
      }
    }
  }

  post {
    success {
      archiveArtifacts artifacts: 'pr-analysis/**/*.json,pr-analysis/**/*.html,pr-analysis/**/*.csv', allowEmptyArchive: true
      sh 'echo "✅ Done — download analysis_report.html from Build Artifacts"'
    }
    failure {
      sh 'echo "❌ Failed — check Console Output above"'
    }
  }
}
